"""Per-node interdisciplinarity scores over a precomputed k-NN index.

Both take INTEGER label arrays (not strings) so the permutation-null engine can shuffle
them cheaply and the scores vectorize.

  DES (Department Escape): fraction of a node's neighbors in a DIFFERENT department.
      Simple, fine-grained, binary boundary-crossing.
  LIS (Latent Interdisciplinarity Score): normalized Shannon entropy of the COLLEGE
      labels among a node's neighbors — captures variety + balance (how many fields,
      how evenly), which DES's binary count cannot.
"""
import numpy as np


def des(nn_idx: np.ndarray, dept_ints: np.ndarray) -> np.ndarray:
    """(N,) fraction of each node's neighbors whose dept differs from its own."""
    neigh = dept_ints[nn_idx]  # (N, k)
    return (neigh != dept_ints[:, None]).mean(axis=1)


def lis(nn_idx: np.ndarray, college_ints: np.ndarray, n_colleges: int) -> np.ndarray:
    """(N,) normalized Shannon entropy of neighbor college labels, in [0, 1].

    1.0 = neighbors spread as evenly as possible across the max number of colleges
    reachable with k neighbors; 0.0 = all neighbors in one college. Normalized by
    log(min(k, n_colleges)) so the ceiling is actually attainable.
    """
    neigh = college_ints[nn_idx]  # (N, k)
    k = neigh.shape[1]
    onehot = np.eye(n_colleges)[neigh]  # (N, k, C)
    p = onehot.sum(axis=1) / k  # (N, C) neighbor college proportions
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(p > 0, p * np.log(p), 0.0)
    entropy = -terms.sum(axis=1)
    return entropy / np.log(min(k, n_colleges))


def rao_stirling(
    nn_idx: np.ndarray, college_ints: np.ndarray, n_colleges: int, dist: np.ndarray
) -> np.ndarray:
    """(N,) Rao-Stirling diversity: sum_ij p_i p_j d_ij over neighbor colleges.

    The disparity-weighted upgrade to LIS: weights each pair of neighbor colleges by
    how DIFFERENT they are (`dist`, a CxC field-distance matrix, e.g. cosine distance
    between college centroids). With dist=1 off-diagonal it reduces to a Simpson-style
    diversity (the LIS family). Documented here; wired into the runner as a fast-follow.
    """
    neigh = college_ints[nn_idx]
    k = neigh.shape[1]
    p = np.eye(n_colleges)[neigh].sum(axis=1) / k  # (N, C)
    # sum_ij p_i p_j d_ij  ==  einsum over the per-node outer product with dist
    return np.einsum("ni,nj,ij->n", p, p, dist)
