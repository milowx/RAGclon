import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;

// Serve static files from the current directory
app.use(express.static(__dirname));

// Serve the main page
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

app.listen(PORT, () => {
    console.log(`🎯 Frontend server running at http://localhost:${PORT}`);
    console.log(`🔗 Make sure your RAG server is running at http://localhost:3001`);
    console.log(`📧 Ready to search through 38,000+ emails!`);
});