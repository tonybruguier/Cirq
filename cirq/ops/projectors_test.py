import re

import numpy as np
import pytest

import cirq


def test_projector_qubit():
    zero_projector = cirq.Projector([[1.0, 0.0]])
    one_projector = cirq.Projector([[0.0, 1.0]])

    np.testing.assert_allclose(cirq.channel(zero_projector),
                               ([[1.0, 0.0], [0.0, 0.0]],))

    np.testing.assert_allclose(cirq.channel(one_projector),
                               ([[0.0, 0.0], [0.0, 1.0]],))


def test_projector_from_np_array():
    zero_projector = cirq.Projector(np.array([[1.0, 0.0]]))
    np.testing.assert_allclose(cirq.channel(zero_projector),
                               ([[1.0, 0.0], [0.0, 0.0]],))


def test_projector_plus():
    plus_projector = cirq.Projector([[1.0, 1.0]])

    np.testing.assert_allclose(cirq.channel(plus_projector),
                               ([[0.5, 0.5], [0.5, 0.5]],))


def test_projector_overcomplete_basis():
    overcomplete_projector = cirq.Projector([[1.0, 0.0], [0.0, 1.0], [1.0,
                                                                      1.0]])

    with pytest.raises(np.linalg.LinAlgError, match="Singular matrix"):
        cirq.channel(overcomplete_projector)


def test_projector_dim2_qubit():
    dim2_projector = cirq.Projector([[1.0, 0.0], [0.0, 1.0]])
    not_colinear_projector = cirq.Projector([[1.0, 0.0], [1.0, 1.0]])

    np.testing.assert_allclose(cirq.channel(dim2_projector),
                               ([[1.0, 0.0], [0.0, 1.0]],))

    np.testing.assert_allclose(cirq.channel(not_colinear_projector),
                               ([[1.0, 0.0], [0.0, 1.0]],))


def test_projector_qutrit():
    zero_projector = cirq.Projector([[1.0, 0.0, 0.0]], qid_shape=[3])
    one_projector = cirq.Projector([[0.0, 1.0, 0.0]], qid_shape=[3])
    two_projector = cirq.Projector([[0.0, 0.0, 1.0]], qid_shape=[3])

    np.testing.assert_allclose(
        cirq.channel(zero_projector),
        ([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],))

    np.testing.assert_allclose(
        cirq.channel(one_projector),
        ([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]],))

    np.testing.assert_allclose(
        cirq.channel(two_projector),
        ([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]],))


def test_bad_constructors():
    with pytest.raises(
            ValueError,
            match=re.escape("Invalid shape (1, 2) for qid_shape [2, 2]")):
        cirq.Projector([[1.0, 0.0]], qid_shape=[2, 2])


def test_get_values():
    d = cirq.Projector([[1.0, 0.0]])

    np.testing.assert_allclose(d._projection_basis_(), [[1.0, 0.0]])
    assert d._qid_shape_() == (2,)
    assert not d._has_unitary_()
    assert not d._is_parameterized_()
    assert d._has_channel_()


def test_repr():
    d = cirq.Projector([[1.0, 0.0]])

    assert d.__repr__(
    ) == "cirq.Projector(projection_basis=[[1.0, 0.0]]),qid_shape=(2,))"
