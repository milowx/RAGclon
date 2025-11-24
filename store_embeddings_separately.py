import json
import pickle
import os
from tqdm import tqdm

def save_embeddings_to_chunks(file_path, chunk_size=10000):
    """Save embeddings to separate pickle files in chunks"""
    
    all_embeddings = {}
    
    print("📊 Loading embeddings from JSONL...")
    with open(file_path, 'r') as file:
        total_lines = sum(1 for _ in open(file_path, 'r'))
        file.seek(0)
        
        for line in tqdm(file, total=total_lines, desc="Extracting embeddings"):
            if line.strip():
                try:
                    email_data = json.loads(line)
                    email_id = email_data.get('id')
                    
                    if email_id and 'embedding' in email_data:
                        all_embeddings[str(email_id)] = email_data['embedding']
                        
                except Exception as e:
                    continue
    
    print(f"✅ Extracted {len(all_embeddings):,} embeddings")
    
    # Save in chunks to avoid huge files
    chunk_num = 0
    items = list(all_embeddings.items())
    
    for i in range(0, len(items), chunk_size):
        chunk = dict(items[i:i + chunk_size])
        filename = f"email_embeddings_chunk_{chunk_num}.pkl"
        
        with open(filename, 'wb') as f:
            pickle.dump(chunk, f)
        
        print(f"💾 Saved chunk {chunk_num}: {len(chunk):,} embeddings -> {filename}")
        chunk_num += 1
    
    # Also save mapping for easy access
    with open("email_ids.txt", "w") as f:
        for email_id in all_embeddings.keys():
            f.write(f"{email_id}\n")
    
    print(f"📝 Saved {len(all_embeddings):,} email IDs to email_ids.txt")
    return len(all_embeddings)

# Run the embedding extraction
total_embeddings = save_embeddings_to_chunks("emails_with_embeddings.jsonl")
print(f"\n🎉 Successfully stored {total_embeddings:,} embeddings in separate files!")
print("💡 You can load these embeddings in your application for vector search")