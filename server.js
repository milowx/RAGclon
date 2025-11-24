import express from 'express';
import cors from 'cors';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import fs from 'fs/promises';
import util from 'util';
import { execFile } from 'child_process';
import { DataAPIClient } from '@datastax/astra-db-ts'; // Correct Node.js driver
import OpenAI from 'openai';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
app.use(cors());
app.use(express.json());

// Load environment variables
import dotenv from 'dotenv';
// Load .env from the parsing directory explicitly so running Node from other CWDs still finds it
dotenv.config({ path: join(__dirname, '.env') });

if (!process.env.OPENAI_API_KEY) {
  console.warn('⚠️ OPENAI_API_KEY not found in environment. Create a .env file in the parsing/ directory with OPENAI_API_KEY=sk-...');
} else {
  console.log('🔒 OpenAI API key loaded from environment');
}

// Initialize OpenAI
const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

// Load embeddings cache
let embeddingsCache = new Map();

const execFileAsync = util.promisify(execFile);

async function loadEmbeddings() {
  console.log('📥 Loading embeddings into memory...');
  try {
    const files = await fs.readdir(__dirname);
    const jsonFiles = files.filter(f => f.startsWith('email_embeddings_chunk_') && f.endsWith('.json'));
    
    for (const file of jsonFiles) {
      const embeddings = JSON.parse(await fs.readFile(join(__dirname, file), 'utf-8'));
      Object.entries(embeddings).forEach(([id, embedding]) => {
        embeddingsCache.set(id, embedding);
      });
    }
    console.log(`✅ Loaded ${embeddingsCache.size} embeddings`);
  } catch (error) {
    console.log('⚠️ No JSON embedding files found. Run convert_embeddings_to_json.py first');
  }
}

// Initialize Astra DB connection with Node.js driver
let collection = null;

async function createAstraOrLocalCollection() {
  const astraToken = process.env.ASTRA_TOKEN || '';
  const astraEndpoint = process.env.ASTRA_ENDPOINT || '';

  if (astraToken && astraEndpoint) {
    try {
      const client = new DataAPIClient(astraToken);
      const db = client.db(astraEndpoint);
      const coll = db.collection('emails');
      console.log('🔗 Astra DB client initialized');
      return coll;
    } catch (err) {
      console.warn('⚠️ Failed to initialize Astra client, falling back to local JSONL. Error:', err.message);
    }
  } else {
    console.warn('⚠️ ASTRA_TOKEN or ASTRA_ENDPOINT not set — using local JSONL fallback for prototyping');
  }

  // Local JSONL fallback: load emails_with_embeddings.jsonl into a Map and expose minimal API
  const localMap = new Map();
  try {
    const jl = await fs.readFile(join(__dirname, 'emails_with_embeddings.jsonl'), 'utf-8');
    const lines = jl.split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);
        const id = obj._id || obj.id || String(obj.id || obj._id || Math.random());
        localMap.set(String(id), obj);
      } catch (e) {
        // skip malformed lines
        continue;
      }
    }
    console.log(`📚 Loaded ${localMap.size} local emails from emails_with_embeddings.jsonl`);
  } catch (e) {
    console.warn('⚠️ Could not read local emails JSONL file for fallback:', e.message);
  }

  // Minimal collection-like API
  return {
    find: (query = {}, options = {}) => {
      // support simple { limit: N } or {$in: ids} for _id
      const limit = options.limit || (query.limit || 0) || 0;
      let results = Array.from(localMap.values());

      if (query && query._id && query._id.$in) {
        const ids = new Set(query._id.$in.map(String));
        results = results.filter(r => ids.has(String(r._id || r.id)));
      }

      if (limit > 0) results = results.slice(0, limit);

      return {
        toArray: async () => results
      };
    },
    findOne: async (q) => {
      const id = q && (q._id || q.id);
      if (!id) return null;
      return localMap.get(String(id)) || null;
    }
  };
}

// initialize collection variable later during startup

async function getDiverseEmailSamples(limit = 20) {
  try {
    const samples = [];
    
    // Sample from different time periods (convert cursor to array properly)
    const recentEmails = await collection.find({}, { limit: Math.floor(limit/4) }).toArray();
    samples.push(...recentEmails);
    
    // Sample with different senders - get unique senders first
    const allEmails = await collection.find({}, { limit: 1000 }).toArray();
    const uniqueSenders = [...new Set(allEmails.map(email => email.meta?.from).filter(Boolean))];
    
    for (const sender of uniqueSenders.slice(0, Math.floor(limit/4))) {
      const senderEmails = await collection.find({ 'meta.from': sender }, { limit: 1 }).toArray();
      if (senderEmails.length > 0) {
        samples.push(senderEmails[0]);
      }
    }
    
    // Sample with different tags/categories
    const taggedEmails = await collection.find({ 'tags.0': { $exists: true } }, { limit: Math.floor(limit/4) }).toArray();
    samples.push(...taggedEmails);
    
    // Remove duplicates and return
    const uniqueSamples = samples.filter((email, index, self) => 
      index === self.findIndex(e => e._id === email._id)
    );
    
    return uniqueSamples.slice(0, limit);
  } catch (error) {
    console.error('Error in diverse sampling:', error);
    // Fallback: just get recent emails
    return await collection.find({}, { limit: limit }).toArray();
  }
}

// REAL OpenAI Embedding Function
async function getQueryEmbedding(query) {
  try {
    const response = await openai.embeddings.create({
      model: "text-embedding-3-small",
      input: query,
    });
    
    return response.data[0].embedding;
  } catch (error) {
    console.error('OpenAI embedding error:', error);
    throw new Error(`Failed to get embedding: ${error.message}`);
  }
}

// REAL OpenAI Chat Completion Function
// Enhanced OpenAI Chat Function for Personal Insights
async function generateChatResponse(message, context, conversationHistory = []) {
  try {
    // Detect if this is a personal analysis request
    const isPersonalAnalysis = message.toLowerCase().includes('about me') || 
                              message.toLowerCase().includes('what can you say') ||
                              message.toLowerCase().includes('infer') ||
                              message.toLowerCase().includes('analyze');

    if (isPersonalAnalysis) {
      // Use a more comprehensive system prompt for personal analysis
      const systemPrompt = `You are an AI assistant analyzing someone's email history to understand their personality, interests, and patterns.

IMPORTANT: Base your analysis ONLY on the provided email context. Do not make assumptions beyond what the emails show.

Analyze these aspects:
1. **Professional Life**: Work, business interests, professional relationships
2. **Personal Interests**: Hobbies, subscriptions, shopping habits
3. **Financial Patterns**: Spending habits, income sources, financial services
4. **Social Connections**: Relationships, communication patterns
5. **Technology Usage**: Apps, services, online presence
6. **Geographic/Language Clues**: Location hints, language preferences
7. **Lifestyle Patterns**: Daily routines, habits, preferences

Be insightful but factual. Only state what you can reasonably infer from the emails.

Email Context:
${context}`;

      const messages = [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: message }
      ];

      const response = await openai.chat.completions.create({
        model: "gpt-4", // Use GPT-4 for better analysis
        messages: messages,
        max_tokens: 800,
        temperature: 0.7,
      });

      return response.choices[0].message.content;
    } else {
      // Original chat logic for specific questions
      const systemPrompt = `You are an AI assistant that knows a lot about this person due to their extensive email history. Have a mysterious and laidback personality.
Use the provided email context to answer questions accurately.

Instructions:
- Base your responses ONLY on the provided email context
- If the context doesn't contain relevant information, say so
- Reference specific emails when possible

Email Context:
${context}`;

      const messages = [
        { role: 'system', content: systemPrompt },
        ...conversationHistory,
        { role: 'user', content: message }
      ];

      const response = await openai.chat.completions.create({
        model: "gpt-4",
        messages: messages,
        max_tokens: 500,
        temperature: 0.7,
      });

      return response.choices[0].message.content;
    }
  } catch (error) {
    console.error('OpenAI chat error:', error);
    throw new Error(`Failed to generate response: ${error.message}`);
  }
}

// API Routes
app.post('/api/search', async (req, res) => {
  try {
    const { query, limit = 10 } = req.body;
    
    if (!query) {
      return res.status(400).json({ error: 'Query is required' });
    }
    
    console.log(`🔍 Searching for: "${query}"`);
    
    // 1. Get query embedding from OpenAI
    const queryEmbedding = await getQueryEmbedding(query);
    
    // 2. Find similar emails using embeddings
    const similarEmails = await findSimilarEmails(queryEmbedding, limit);
    
    // 3. Format response
    const results = similarEmails.map(email => ({
      id: email._id,
      subject: email.meta?.subject || 'No subject',
      from: email.meta?.from || 'Unknown sender',
      timestamp: email.timestamp,
      text: email.text || '',
      similarity: email.similarity
    }));
    
    res.json({ 
      results, 
      total: similarEmails.length,
      query 
    });
  } catch (error) {
    console.error('Search error:', error);
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/search-universal', async (req, res) => {
  const { 
    query, 
    limit = 10, 
    maxAgeDays = 180 
  } = req.body;
  
  const results = await universalSemanticSearch(query, {
    limit,
    maxDaysOld: maxAgeDays
  });
  
  res.json({ 
    results,
    searchType: 'universal_semantic'
  });
});

app.post('/api/chat', async (req, res) => {
  try {
    const { message, conversationHistory = [] } = req.body;
    
    if (!message) {
      return res.status(400).json({ error: 'Message is required' });
    }
    
    console.log(`💬 Chat request: "${message}"`);
    
    // Check if this is a personal analysis request
    const isPersonalAnalysis = message.toLowerCase().includes('about me') || 
                              message.toLowerCase().includes('what can you say') ||
                              message.toLowerCase().includes('infer') ||
                              message.toLowerCase().includes('analyze') ||
                              message.toLowerCase().includes('profile');
    
    let contextEmails;
    let context;
    
    if (isPersonalAnalysis) {
      // Use the new analysis endpoint for personal questions
      console.log('🔍 Personal analysis detected - using broad sampling');
      contextEmails = await getBroadEmailSample(15);
      context = contextEmails.map(email => 
        `From: ${email.meta?.from || 'Unknown'}\nSubject: ${email.meta?.subject || 'No subject'}\nDate: ${email.timestamp}\nContent: ${email.text?.substring(0, 300) || ''}`
      ).join('\n\n');
    } else {
      // Use semantic search for specific questions
      const queryEmbedding = await getQueryEmbedding(message);
      contextEmails = await findSimilarEmails(queryEmbedding, 5);
      context = contextEmails.map(email => 
        `From: ${email.meta?.from || 'Unknown'}\nSubject: ${email.meta?.subject || 'No subject'}\nDate: ${email.timestamp}\nContent: ${email.text?.substring(0, 500) || ''}`
      ).join('\n\n');
    }
    
    console.log(`📧 Using ${contextEmails.length} emails as context`);
    
    // Generate response
    const response = await generateChatResponse(message, context, conversationHistory);
    
    res.json({ 
      response, 
      contextSources: contextEmails.length,
      analysisType: isPersonalAnalysis ? 'personal_insights' : 'specific_query',
      sources: contextEmails.map(email => ({
        id: email._id,
        subject: email.meta?.subject,
        from: email.meta?.from,
        timestamp: email.timestamp
      }))
    });
  } catch (error) {
    console.error('Chat error:', error);
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'OK', 
    embeddingsLoaded: embeddingsCache.size,
    timestamp: new Date().toISOString()
  });
});

async function findSimilarEmails(queryEmbedding, limit = 10) {
  // Query the local FAISS index via the Python CLI `embeddings_index.py`.
  // This avoids loading all embeddings into Node memory and uses the optimized FAISS search.
  try {
    const qvecPath = join(__dirname, `qvec_${Date.now()}.json`);
    await fs.writeFile(qvecPath, JSON.stringify(queryEmbedding), 'utf-8');

    const args = [
      'embeddings_index.py',
      'query',
      '--index-file', 'email_index.faiss',
      '--map-file', 'id_map.json',
      '--vector-file', qvecPath,
      '--topk', String(limit)
    ];

    // Execute the Python CLI in the parsing directory
    const { stdout, stderr } = await execFileAsync('python3', args, { cwd: __dirname, maxBuffer: 10 * 1024 * 1024 });
    if (stderr && stderr.trim()) {
      console.warn('FAISS CLI stderr:', stderr);
    }

    let results = [];
    try {
      results = JSON.parse(stdout);
    } catch (e) {
      console.error('Failed to parse FAISS CLI output:', e, 'raw:', stdout);
      throw e;
    }

    const ids = results.map(r => r.id).filter(Boolean);
    if (ids.length === 0) return [];

    // Batch fetch emails from Astra by ids
    let emails = [];
    try {
      emails = await collection.find({ _id: { $in: ids } }).toArray();
    } catch (err) {
      console.error('Error fetching emails by ids:', err.message);
      // Fallback: try fetching individually
      const temp = [];
      for (const id of ids) {
        try {
          const e = await collection.findOne({ _id: id });
          if (e) temp.push(e);
        } catch (ee) {
          console.warn('Fallback fetch failed for', id, ee.message);
        }
      }
      emails = temp;
    }

    // Map results back to ordered list with similarity
    const emailMap = new Map(emails.map(e => [String(e._id), e]));
    const emailDetails = [];
    for (const r of results) {
      const e = emailMap.get(String(r.id));
      if (e) {
        e.similarity = r.score;
        emailDetails.push(e);
      }
    }

    // Cleanup temp vector file
    try { await fs.unlink(qvecPath); } catch (_) {}

    return emailDetails;
  } catch (error) {
    console.error('findSimilarEmails error:', error);
    throw error;
  }
}
app.post('/api/analyze-profile', async (req, res) => {
  try {
    console.log('🧠 Starting comprehensive profile analysis...');
    
    // Get a broad sample of emails for analysis
    const analysisEmails = await getBroadEmailSample(25);
    
    // Build comprehensive context
    const context = analysisEmails.map(email => 
      `From: ${email.meta?.from || 'Unknown'}\nSubject: ${email.meta?.subject || 'No subject'}\nDate: ${email.timestamp}\nContent: ${email.text?.substring(0, 400) || ''}`
    ).join('\n\n---\n\n');
    
    console.log(`📧 Using ${analysisEmails.length} diverse emails for analysis`);
    
    const systemPrompt = `You are an AI assistant analyzing someone's email history to understand their personality, interests, work, and lifestyle.

IMPORTANT: Base your analysis ONLY on the provided email context. Be insightful but factual.

Analyze these aspects in detail:
1. **Professional Life & Work**: Career, business interests, professional relationships, income sources
2. **Personal Interests & Hobbies**: Subscriptions, shopping habits, entertainment, passions
3. **Financial Patterns**: Spending habits, financial services, income opportunities
4. **Social & Communication Patterns**: Relationships, communication style, social networks
5. **Technology & Online Presence**: Apps, services, digital footprint
6. **Lifestyle & Habits**: Daily routines, preferences, behaviors
7. **Goals & Aspirations**: What they seem to be working toward

Provide a comprehensive analysis that paints a picture of who this person is based on their email patterns.

Email Context:
${context}`;

    const response = await openai.chat.completions.create({
      model: "gpt-4",
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: "Please analyze my profile based on my email history." }
      ],
      max_tokens: 1000,
      temperature: 0.7,
    });

    const analysis = response.choices[0].message.content;
    
    // Categorize the sample emails for transparency
    const categorizedEmails = analysisEmails.map(email => {
      const subject = email.meta?.subject?.toLowerCase() || '';
      const text = email.text?.toLowerCase() || '';
      let category = 'other';
      
      if (subject.includes('survey') || text.includes('survey')) category = 'surveys';
      else if (subject.includes('music') || text.includes('music')) category = 'music';
      else if (subject.includes('amazon') || text.includes('amazon')) category = 'shopping';
      else if (subject.includes('spotify') || text.includes('spotify')) category = 'entertainment';
      else if (subject.includes('paid') || text.includes('$')) category = 'income';
      else if (subject.includes('newsletter') || text.includes('subscribe')) category = 'newsletters';
      else if (subject.includes('work') || subject.includes('job') || subject.includes('career')) category = 'professional';
      
      return {
        id: email._id,
        subject: email.meta?.subject,
        from: email.meta?.from,
        category: category
      };
    });
    
    res.json({ 
      analysis,
      samplesUsed: analysisEmails.length,
      emailExamples: categorizedEmails
    });
  } catch (error) {
    console.error('Profile analysis error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Helper function to get broad email sample
async function getBroadEmailSample(limit = 25) {
  try {
    // Get a large batch and randomly select from it
    const batchSize = Math.min(500, limit * 5);
    const allEmails = await collection.find({}, { limit: batchSize }).toArray();
    
    // If we don't have enough, return what we have
    if (allEmails.length <= limit) {
      return allEmails;
    }
    
    // Shuffle array and take sample
    const shuffled = [...allEmails];
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    
    return shuffled.slice(0, limit);
  } catch (error) {
    console.error('Error in sampling:', error);
    // Fallback: just get the most recent emails
    return await collection.find({}, { limit: limit }).toArray();
  }
}

// Helper function to categorize emails
function categorizeEmail(email) {
  const subject = email.meta?.subject?.toLowerCase() || '';
  const text = email.text?.toLowerCase() || '';
  
  if (subject.includes('survey') || text.includes('survey')) return 'surveys';
  if (subject.includes('music') || text.includes('music')) return 'music';
  if (subject.includes('amazon') || text.includes('amazon')) return 'shopping';
  if (subject.includes('spotify') || text.includes('spotify')) return 'entertainment';
  if (subject.includes('paid') || text.includes('$')) return 'income';
  if (subject.includes('newsletter') || text.includes('subscribe')) return 'newsletters';
  
  return 'other';
}

function cosineSimilarity(a, b) {
  if (a.length !== b.length) {
    throw new Error('Vectors must have same length');
  }
  
  const dotProduct = a.reduce((sum, val, i) => sum + val * b[i], 0);
  const magnitudeA = Math.sqrt(a.reduce((sum, val) => sum + val * val, 0));
  const magnitudeB = Math.sqrt(b.reduce((sum, val) => sum + val * val, 0));
  
  if (magnitudeA === 0 || magnitudeB === 0) {
    return 0;
  }
  
  return dotProduct / (magnitudeA * magnitudeB);
}

// Universal semantic search function
async function universalSemanticSearch(query, options = {}) {
  const {
    limit = 10,
    maxDaysOld = 365,
    semanticBroadening = true
  } = options;
  
  // Step 1: Create language-agnostic query
  const universalQuery = await createUniversalQuery(query);
  
  // Step 2: Get universal embedding
  const queryEmbedding = await getQueryEmbedding(universalQuery);
  
  // Step 3: Find similar emails
  const allResults = await findSimilarEmails(queryEmbedding, limit * 2);
  
  // Step 4: Apply recency filtering if needed
  let filteredResults = allResults;
  if (maxDaysOld) {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - maxDaysOld);
    filteredResults = allResults.filter(email => 
      new Date(email.timestamp) > cutoffDate
    );
  }
  
  return filteredResults.slice(0, limit);
}

// Core magic: Make any query language-agnostic
async function createUniversalQuery(query) {
  const language = detectLanguageSimple(query);
  
  let universalQuery = query;
  
  // Add cross-language context
  if (language === 'en') {
    universalQuery += ` | encuesta pagada remuneración dinero`;
  } else if (language === 'es') {
    universalQuery += ` | paid survey money compensation earnings`;
  }
  
  // Add semantic broadening for better concept matching
  universalQuery += ` payment income financial reward`;
  
  return universalQuery;
}

// Simple language detection
function detectLanguageSimple(text) {
  const spanishWords = ['el', 'la', 'de', 'que', 'y', 'en', 'un', 'es', 'se', 'no', 'te', 'lo', 'le', 'su', 'por', 'más', 'con', 'una', 'para'];
  const englishWords = ['the', 'and', 'of', 'to', 'a', 'in', 'is', 'you', 'that', 'it', 'he', 'was', 'for', 'on', 'are', 'as', 'with', 'his', 'they'];
  
  const words = text.toLowerCase().split(/\s+/);
  
  let spanishCount = 0;
  let englishCount = 0;
  
  for (const word of words) {
    if (spanishWords.includes(word)) spanishCount++;
    if (englishWords.includes(word)) englishCount++;
  }
  
  return spanishCount > englishCount ? 'es' : 'en';
}

// Start server
async function startServer() {
  await loadEmbeddings();
  collection = await createAstraOrLocalCollection();
  
  const PORT = process.env.PORT || 3001;
  app.listen(PORT, () => {
    console.log(`🚀 Email RAG server running on port ${PORT}`);
    console.log(`📊 ${embeddingsCache.size} embeddings loaded`);
    console.log(`🤖 OpenAI integration: ACTIVE`);
    console.log(`🔗 Health check: http://localhost:${PORT}/api/health`);
  });
}

startServer().catch(console.error);