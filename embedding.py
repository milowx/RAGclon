import json
import openai
import tiktoken
import os

# Set your OpenAI API key
openai.api_key = "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"  # REPLACE WITH YOUR ACTUAL KEY

def truncate_text(text: str, max_tokens: int = 8000) -> str:
    """Truncate text to fit within token limit"""
    encoding = tiktoken.encoding_for_model("text-embedding-3-small")
    tokens = encoding.encode(text)
    
    if len(tokens) > max_tokens:
        tokens = tokens[:max_tokens]
        text = encoding.decode(tokens)
        print(f"Truncated email from {len(tokens)} to {max_tokens} tokens")
    
    return text

def embed_emails(input_file: str, output_file: str):
    """Simple script to add embeddings to your cleaned emails"""
    
    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:
        
        for i, line in enumerate(infile):
            try:
                email_data = json.loads(line.strip())
                
                # Prepare text for embedding
                subject = email_data.get('meta', {}).get('subject', '')
                text = email_data.get('text', '')
                embedding_text = f"Subject: {subject}\nContent: {text}"
                
                # Truncate if too long
                embedding_text = truncate_text(embedding_text)
                
                # Get embedding
                response = openai.embeddings.create(
                    model="text-embedding-3-small",
                    input=embedding_text
                )
                
                # Add embedding to email data
                email_data['embedding'] = response.data[0].embedding
                
                # Write to new file
                outfile.write(json.dumps(email_data, ensure_ascii=False) + '\n')
                
                if (i + 1) % 100 == 0:
                    print(f"Embedded {i + 1} emails...")
                    
            except Exception as e:
                print(f"Error with email {i + 1}: {e}")
                continue
    
    print(f"Done! Embedded emails saved to {output_file}")

# RUN THIS
if __name__ == "__main__":
    embed_emails(
        input_file="emails_ultra_clean.jsonl",  # Your cleaned file
        output_file="emails_with_embeddings.jsonl"  # New file with embeddings
    )