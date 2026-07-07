"""Shuffled-label permutation null -> z-scores (the reusable metric spine).

The core idea: to ask "is department D unusually interdisciplinary?", we can't compare
its raw score to other departments (they're different sizes, and size alone inflates
same-group neighbor rates by +0.68 here). Instead we reshuffle the labels many times
WHILE PRESERVING how many nodes carry each label, recompute the score, and ask how many
standard deviations the REAL score sits above that size-matched random baseline. That
z-score is size-controlled by construction.

One engine serves DES, LIS, and every later modality (faculty, buildings).
"""
import numpy as np


def _group_mean(values: np.ndarray, group_ints: np.ndarray, n_groups: int) -> np.ndarray:
    """Mean of `values` within each integer group (bincount = fast group-by)."""
    sums = np.bincount(group_ints, weights=values, minlength=n_groups)
    counts = np.bincount(group_ints, minlength=n_groups)
    return sums / np.where(counts > 0, counts, 1.0)


def _zscore(observed: np.ndarray, null: np.ndarray) -> np.ndarray:
    """(observed - null_mean) / null_std, with std=0 guarded to 1."""
    sd = null.std(axis=0)
    return (observed - null.mean(axis=0)) / np.where(sd > 0, sd, 1.0)


def permutation_null(
    score_fn,
    perm_labels: np.ndarray,
    n_groups: int,
    n_perm: int = 1000,
    seed: int = 0,
) -> dict:
    """Permute `perm_labels` (size-preserving) and z-score at node and group level.

    score_fn(labels) -> (N,) per-node scores.
      - If score_fn USES the labels (e.g. DES, whose 'own department' is permuted),
        the per-node null varies and node_z is meaningful (the per-course heatmap).
      - If score_fn IGNORES them (e.g. a fixed LIS vector that we only re-GROUP by a
        permuted department), node_z is degenerate; only group_z is meaningful — that
        is the size-controlled "is this dept's mean score special?" test.

    Grouping is always by the (permuted) labels, so group_z compares each real group to
    random groups OF THE SAME SIZE.
    """
    rng = np.random.default_rng(seed)
    obs_node = score_fn(perm_labels)
    obs_group = _group_mean(obs_node, perm_labels, n_groups)

    node_null = np.empty((n_perm, len(perm_labels)))
    group_null = np.empty((n_perm, n_groups))
    perm = perm_labels.copy()
    for i in range(n_perm):
        rng.shuffle(perm)  # in-place permutation preserves group sizes exactly
        s = score_fn(perm)
        node_null[i] = s
        group_null[i] = _group_mean(s, perm, n_groups)

    return {
        "obs_node": obs_node,
        "node_z": _zscore(obs_node, node_null),
        "obs_group": obs_group,
        "group_z": _zscore(obs_group, group_null),
    }
