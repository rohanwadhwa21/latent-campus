"""k-nearest-neighbor indices from a (unit-normalized) embedding matrix.

Same cosine machinery as scripts/nn_query.py: vectors are unit-normalized, so the
dot product emb @ emb.T IS cosine similarity. O(N^2) — fine for N~5k (the full N x N
similarity matrix is ~90 MB float32 at N=4.7k).
"""
import numpy as np


def knn_indices(emb: np.ndarray, k: int = 10) -> np.ndarray:
    """Return (N, k) int array of each row's top-k neighbors, self excluded.

    Neighbors are sorted by descending cosine similarity. argpartition pulls the top-k
    cheaply (O(N) per row), then we sort just those k.
    """
    if k >= emb.shape[0]:
        raise ValueError(f"k={k} must be < n_points={emb.shape[0]}")
    sims = emb @ emb.T
    np.fill_diagonal(sims, -np.inf)  # never let a node be its own neighbor
    part = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
    rows = np.arange(emb.shape[0])[:, None]
    order = np.argsort(-sims[rows, part], axis=1)
    return part[rows, order]
