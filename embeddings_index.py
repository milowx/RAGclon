"""Build and query a local FAISS index for email embeddings.

Usage:
  python embeddings_index.py build --input emails_with_embeddings.jsonl --index-file email_index.faiss --map-file id_map.json
  python embeddings_index.py query --index-file email_index.faiss --map-file id_map.json --vector-file qvec.json --topk 10

The script expects each line in the input JSONL to contain at least an `id` (or `_id`) and an `embedding` array.
It will store a FAISS index (flat, inner-product on L2-normalized vectors) and a JSON mapping of integer positions to email ids.
"""
import argparse
import json
import os
import sys
try:
    from tqdm import tqdm
except Exception:
    # Fallback: simple passthrough if tqdm is not installed
    def tqdm(x, **kwargs):
        return x

try:
    import faiss
except Exception as e:
    raise RuntimeError("faiss is required. Install faiss-cpu in your environment.")

import numpy as np


def build_index(jsonl_path, index_path, mapping_path, dim_override=None):
    ids = []
    vectors = []

    if not os.path.exists(jsonl_path):
        raise FileNotFoundError(jsonl_path)

    # Read embeddings
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in tqdm(f, desc='Reading embeddings'):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            emb = None
            if 'embedding' in obj:
                emb = obj['embedding']
            elif 'embeddings' in obj:
                # handle alternate key
                emb = obj['embeddings']

            if emb is None:
                continue

            # get id
            eid = obj.get('id') or obj.get('_id') or obj.get('email_id')
            if eid is None:
                # skip objects without id
                continue

            ids.append(str(eid))
            vectors.append(np.array(emb, dtype='float32'))

    if not vectors:
        raise RuntimeError('No embeddings found in the provided file')

    mat = np.vstack(vectors)

    # Optionally check dimension
    dim = mat.shape[1]
    if dim_override and dim_override != dim:
        print(f"Warning: dimension override {dim_override} != detected {dim}")

    # Normalize vectors to unit length to use inner-product as cosine similarity
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat = mat / norms

    index = faiss.IndexFlatIP(dim)
    index.add(mat)

    # Save index and mapping
    faiss.write_index(index, index_path)

    id_map = {str(i): ids[i] for i in range(len(ids))}
    with open(mapping_path, 'w', encoding='utf-8') as mf:
        json.dump(id_map, mf)

    print(f"Built FAISS index with {len(ids)} vectors -> {index_path}")
    print(f"Saved id mapping -> {mapping_path}")


def query_index(index_path, mapping_path, query_vector, topk=10):
    if not os.path.exists(index_path):
        raise FileNotFoundError(index_path)
    if not os.path.exists(mapping_path):
        raise FileNotFoundError(mapping_path)

    index = faiss.read_index(index_path)

    with open(mapping_path, 'r', encoding='utf-8') as mf:
        id_map = json.load(mf)

    q = np.array(query_vector, dtype='float32')
    if q.ndim == 1:
        q = q.reshape(1, -1)

    # normalize
    q_norm = np.linalg.norm(q, axis=1, keepdims=True)
    q_norm[q_norm == 0] = 1.0
    q = q / q_norm

    scores, indices = index.search(q, topk)

    results = []
    for s_list, idx_list in zip(scores, indices):
        for score, idx in zip(s_list, idx_list):
            if idx == -1:
                continue
            eid = id_map.get(str(int(idx)))
            results.append({'id': eid, 'score': float(score)})

    return results


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')

    pbuild = sub.add_parser('build')
    pbuild.add_argument('--input', required=True, help='JSONL with embeddings')
    pbuild.add_argument('--index-file', required=True, help='Output FAISS index file')
    pbuild.add_argument('--map-file', required=True, help='Output id map JSON file')
    pbuild.add_argument('--dim', type=int, default=None)

    pquery = sub.add_parser('query')
    pquery.add_argument('--index-file', required=True)
    pquery.add_argument('--map-file', required=True)
    pquery.add_argument('--vector-file', required=True, help='JSON file with array vector or .npy')
    pquery.add_argument('--topk', type=int, default=10)

    args = parser.parse_args()

    if args.cmd == 'build':
        build_index(args.input, args.index_file, args.map_file, dim_override=args.dim)
    elif args.cmd == 'query':
        # load vector
        vfile = args.vector_file
        if vfile.endswith('.npy'):
            qvec = np.load(vfile)
        else:
            with open(vfile, 'r', encoding='utf-8') as vf:
                qvec = json.load(vf)

        results = query_index(args.index_file, args.map_file, qvec, topk=args.topk)
        print(json.dumps(results, indent=2))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
