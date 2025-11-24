"""FastAPI wrapper around the local FAISS index.

Endpoints:
- POST /search  -> { embedding: [...], topk: int } returns list of {id, score}
- GET  /health  -> index status

This service loads `email_index.faiss` and `id_map.json` from the same directory on startup.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import os
import json
import numpy as np

try:
    import faiss
except Exception:
    faiss = None

app = FastAPI()

INDEX = None
ID_MAP = {}
DIM = None


class SearchRequest(BaseModel):
    embedding: List[float]
    topk: int = 10


@app.on_event("startup")
async def startup_event():
    global INDEX, ID_MAP, DIM
    cwd = os.path.dirname(__file__)
    index_path = os.path.join(cwd, 'email_index.faiss')
    map_path = os.path.join(cwd, 'id_map.json')

    if faiss is None:
        print('FAISS library not available. Install faiss-cpu to enable index.')
        INDEX = None
        return

    if not os.path.exists(index_path) or not os.path.exists(map_path):
        print('FAISS index or id_map.json not found in parsing/. Please build the index first.')
        INDEX = None
        return

    INDEX = faiss.read_index(index_path)
    with open(map_path, 'r', encoding='utf-8') as mf:
        ID_MAP = json.load(mf)

    try:
        DIM = INDEX.d
    except Exception:
        DIM = None

    print(f'Loaded FAISS index {index_path} (dim={DIM}, n={INDEX.ntotal})')


@app.post('/search')
async def search(req: SearchRequest):
    if INDEX is None:
        raise HTTPException(status_code=503, detail='Index not loaded')

    q = np.array(req.embedding, dtype='float32')
    if q.ndim == 1:
        q = q.reshape(1, -1)

    if DIM is not None and q.shape[1] != DIM:
        raise HTTPException(status_code=400, detail=f'Embedding dimension mismatch: expected {DIM}, got {q.shape[1]}')

    # normalize to unit vectors (FAISS IP index expects normalized vectors for cosine)
    norms = np.linalg.norm(q, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    q = q / norms

    scores, indices = INDEX.search(q, req.topk)

    results = []
    for s_list, idx_list in zip(scores, indices):
        for score, idx in zip(s_list, idx_list):
            if idx == -1:
                continue
            eid = ID_MAP.get(str(int(idx)))
            results.append({'id': eid, 'score': float(score)})

    return {'results': results}


@app.get('/health')
async def health():
    return {'status': 'ok', 'index_loaded': INDEX is not None, 'dim': DIM}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('index_api:app', host='127.0.0.1', port=8000, log_level='info')
