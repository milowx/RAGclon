import pickle
import json
import glob

# Convert all pickle files to JSON for Node.js
for pkl_file in glob.glob("email_embeddings_chunk_*.pkl"):
    with open(pkl_file, 'rb') as f:
        embeddings = pickle.load(f)
    
    json_file = pkl_file.replace('.pkl', '.json')
    with open(json_file, 'w') as f:
        json.dump(embeddings, f)
    
    print(f"✅ Converted {pkl_file} -> {json_file}")

print("🎉 All embeddings converted to JSON!")