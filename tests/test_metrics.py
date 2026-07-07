"""Tests for the interdisciplinarity metrics on synthetic data with known answers."""
import numpy as np

from latent_campus.metrics.diversity import des, lis, rao_stirling
from latent_campus.metrics.knn import knn_indices
from latent_campus.metrics.nulls import permutation_null


class TestKnn:
    def test_excludes_self_and_finds_nearest(self):
        # two tight pairs: 0~1 and 2~3
        emb = np.array([[1, 0], [1, 0.05], [0, 1], [0.05, 1]], dtype=float)
        emb /= np.linalg.norm(emb, axis=1, keepdims=True)
        nn = knn_indices(emb, k=1)
        assert nn.shape == (4, 1)
        assert nn[0, 0] == 1 and nn[1, 0] == 0  # self never appears
        assert nn[2, 0] == 3 and nn[3, 0] == 2


class TestDes:
    def test_known_values(self):
        nn = np.array([[1, 2], [0, 2], [0, 1]])
        dept = np.array([0, 0, 1])
        # node0 neighbors depts [0,1] vs own 0 -> 0.5; node2 neighbors [0,0] vs 1 -> 1.0
        np.testing.assert_allclose(des(nn, dept), [0.5, 0.5, 1.0])

    def test_bridge_escapes_more_than_cluster_core(self):
        rng = np.random.default_rng(0)
        ang = np.concatenate(
            [rng.normal(0.0, 0.1, 15), rng.normal(np.pi / 2, 0.1, 15), [np.pi / 4]]
        )
        emb = np.c_[np.cos(ang), np.sin(ang)]  # unit-norm by construction
        dept = np.array([0] * 15 + [1] * 15 + [0])  # last point = planted bridge
        d = des(knn_indices(emb, k=6), dept)
        assert d[-1] > d[:15].mean()  # bridge crosses more than the cluster-0 average


class TestLis:
    def test_known_values(self):
        nn = np.array([[1, 2], [0, 2], [0, 1]])
        college = np.array([0, 0, 1])
        # node0 neighbors colleges [0,1] -> max entropy -> 1.0; node2 [0,0] -> 0.0
        np.testing.assert_allclose(lis(nn, college, n_colleges=2), [1.0, 1.0, 0.0])

    def test_rao_stirling_reduces_to_simpson(self):
        # with dist = 1 off-diagonal / 0 on-diagonal, RS == 1 - sum p_i^2 (Simpson)
        nn = np.array([[1, 2], [0, 2], [0, 1]])
        college = np.array([0, 0, 1])
        C = 2
        dist = 1.0 - np.eye(C)
        rs = rao_stirling(nn, college, C, dist)
        p = np.eye(C)[college[nn]].sum(axis=1) / nn.shape[1]
        simpson = 1.0 - (p**2).sum(axis=1)
        np.testing.assert_allclose(rs, simpson)


class TestPermutationNull:
    def test_mean_z_near_zero_under_random_labels(self):
        rng = np.random.default_rng(1)
        emb = rng.normal(size=(60, 8))
        emb /= np.linalg.norm(emb, axis=1, keepdims=True)
        nn = knn_indices(emb, k=8)
        labels = rng.integers(0, 5, size=60)  # random -> no real structure
        out = permutation_null(lambda lab: des(nn, lab), labels, n_groups=5, n_perm=200, seed=2)
        # z-scores must center near zero when labels carry no real signal
        assert abs(out["node_z"].mean()) < 0.5
        assert out["obs_node"].shape == (60,) and out["group_z"].shape == (5,)

    def test_deterministic_with_seed(self):
        rng = np.random.default_rng(3)
        emb = rng.normal(size=(40, 6))
        emb /= np.linalg.norm(emb, axis=1, keepdims=True)
        nn = knn_indices(emb, k=5)
        labels = rng.integers(0, 4, size=40)
        a = permutation_null(lambda lab: des(nn, lab), labels, 4, n_perm=50, seed=7)
        b = permutation_null(lambda lab: des(nn, lab), labels, 4, n_perm=50, seed=7)
        np.testing.assert_array_equal(a["group_z"], b["group_z"])
