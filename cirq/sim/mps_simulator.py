# Copyright 2019 The Cirq Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""An MPS simulator.

This is based on this paper:
https://arxiv.org/abs/2002.07730

TODO(tonybruguier): Currently, numpy is used for tensor computations. For speed
switch to QIM for speed.
"""

import collections
import math
from typing import Any, cast, Dict, List, Iterator, Sequence

import numpy as np

import cirq
from cirq import circuits, study, ops, protocols, value
from cirq.sim import simulator


class MPSSimulator(simulator.SimulatesSamples, simulator.SimulatesIntermediateState):
    """An efficient simulator for MPS circuits."""

    def __init__(self, seed: 'cirq.RANDOM_STATE_OR_SEED_LIKE' = None):
        """Creates instance of `MPSSimulator`.

        Args:
            seed: The random seed to use for this simulator.
        """
        self.init = True
        self._prng = value.parse_random_state(seed)

    def _base_iterator(
        self, circuit: circuits.Circuit, qubit_order: ops.QubitOrderOrList, initial_state: int
    ) -> Iterator['cirq.MPSSimulatorStepResult']:
        """Iterator over MPSSimulatorStepResult from Moments of a Circuit

        Args:
            circuit: The circuit to simulate.
            qubit_order: Determines the canonical ordering of the qubits. This
                is often used in specifying the initial state, i.e. the
                ordering of the computational basis states.
            initial_state: The initial state for the simulation in the
                computational basis. Represented as a big endian int.


        Yields:
            MPSStepResult from simulating a Moment of the Circuit.
        """
        qubits = ops.QubitOrder.as_qubit_order(qubit_order).order_for(circuit.all_qubits())

        qubit_map = {q: i for i, q in enumerate(qubits)}

        if len(circuit) == 0:
            yield MPSSimulatorStepResult(
                measurements={}, state=MPSState(qubit_map, initial_state=initial_state)
            )
            return

        state = MPSState(qubit_map, initial_state=initial_state)

        for moment in circuit:
            measurements: Dict[str, List[int]] = collections.defaultdict(list)

            for op in moment:
                if isinstance(op.gate, ops.MeasurementGate):
                    key = str(protocols.measurement_key(op))
                    measurements[key].extend(state.perform_measurement(op.qubits, self._prng))
                elif protocols.has_unitary(op):
                    state.apply_unitary(op)
                else:
                    raise NotImplementedError(f"Unrecognized operation: {op!r}")

            yield MPSSimulatorStepResult(measurements=measurements, state=state)

    def _simulator_iterator(
        self,
        circuit: circuits.Circuit,
        param_resolver: study.ParamResolver,
        qubit_order: ops.QubitOrderOrList,
        initial_state: int,
    ) -> Iterator:
        """See definition in `cirq.SimulatesIntermediateState`.

        Args:
            inital_state: An integer specifying the inital
            state in the computational basis.
        """
        param_resolver = param_resolver or study.ParamResolver({})
        resolved_circuit = protocols.resolve_parameters(circuit, param_resolver)
        self._check_all_resolved(resolved_circuit)
        actual_initial_state = 0 if initial_state is None else initial_state

        return self._base_iterator(resolved_circuit, qubit_order, actual_initial_state)

    def _create_simulator_trial_result(
        self,
        params: study.ParamResolver,
        measurements: Dict[str, np.ndarray],
        final_simulator_state,
    ):

        return MPSTrialResult(
            params=params, measurements=measurements, final_simulator_state=final_simulator_state
        )

    def _run(
        self, circuit: circuits.Circuit, param_resolver: study.ParamResolver, repetitions: int
    ) -> Dict[str, List[np.ndarray]]:

        param_resolver = param_resolver or study.ParamResolver({})
        resolved_circuit = protocols.resolve_parameters(circuit, param_resolver)
        self._check_all_resolved(resolved_circuit)

        measurements = {}  # type: Dict[str, List[np.ndarray]]
        if repetitions == 0:
            for _, op, _ in resolved_circuit.findall_operations_with_gate_type(ops.MeasurementGate):
                measurements[protocols.measurement_key(op)] = np.empty([0, 1])

        for _ in range(repetitions):
            all_step_results = self._base_iterator(
                resolved_circuit, qubit_order=ops.QubitOrder.DEFAULT, initial_state=0
            )

            for step_result in all_step_results:
                for k, v in step_result.measurements.items():
                    if not k in measurements:
                        measurements[k] = []
                    measurements[k].append(np.array(v, dtype=int))

        return {k: np.array(v) for k, v in measurements.items()}

    def _check_all_resolved(self, circuit):
        """Raises if the circuit contains unresolved symbols."""
        if protocols.is_parameterized(circuit):
            unresolved = [
                op for moment in circuit for op in moment if protocols.is_parameterized(op)
            ]
            raise ValueError(
                'Circuit contains ops whose symbols were not specified in '
                'parameter sweep. Ops: {}'.format(unresolved)
            )


class MPSTrialResult(simulator.SimulationTrialResult):
    def __init__(
        self,
        params: study.ParamResolver,
        measurements: Dict[str, np.ndarray],
        final_simulator_state: 'MPSState',
    ) -> None:
        super().__init__(
            params=params, measurements=measurements, final_simulator_state=final_simulator_state
        )

        self.final_state = final_simulator_state

    def __str__(self) -> str:
        samples = super().__str__()
        final = self._final_simulator_state
        return f'measurements: {samples}\noutput state: {final}'


class MPSSimulatorStepResult(simulator.StepResult):
    """A `StepResult` that includes `StateVectorMixin` methods."""

    def __init__(self, state, measurements):
        """Results of a step of the simulator.
        Attributes:
            state: A MPSState
            measurements: A dictionary from measurement gate key to measurement
                results, ordered by the qubits that the measurement operates on.
            qubit_map: A map from the Qubits in the Circuit to the the index
                of this qubit for a canonical ordering. This canonical ordering
                is used to define the state vector (see the state_vector()
                method).
        """
        self.measurements = measurements
        self.state = state.copy()

    def __str__(self) -> str:
        def bitstring(vals):
            return ','.join(str(v) for v in vals)

        results = sorted([(key, bitstring(val)) for key, val in self.measurements.items()])

        if len(results) == 0:
            measurements = ''
        else:
            measurements = ' '.join([f'{key}={val}' for key, val in results]) + '\n'

        final = self.state

        return f'{measurements}{final}'

    def _simulator_state(self):
        return self.state

    def sample(
        self,
        qubits: List[ops.Qid],
        repetitions: int = 1,
        seed: 'cirq.RANDOM_STATE_OR_SEED_LIKE' = None,
    ) -> np.ndarray:

        measurements: List[int] = []

        for _ in range(repetitions):
            measurements.append(
                self.state.perform_measurement(
                    qubits, value.parse_random_state(seed), collapse_state_vector=False
                )
            )

        return np.array(measurements, dtype=int)


@value.value_equality
class MPSState:
    """A state of the MPS simulation."""

    def __init__(self, qubit_map, initial_state=0):
        self.qubit_map = qubit_map
        self.M = []
        for qubit in qubit_map.keys():
            d = qubit.dimension
            x = np.zeros(
                (
                    1,  # row-previous
                    1,  # row-current
                    1,  # col-previous
                    1,  # col-current
                    d,
                )
            )
            # Note that for simplicity of writing the code, we do not quite use
            # the exact same notation as in the paper. Instead, the qubits on
            # the edge still have a \mu referring to a dummy, non present,
            # qubit. The value of these \mu is always 0.
            x[0, 0, 0, 0, (initial_state % d)] = 1.0
            self.M.append(x)
            initial_state = initial_state // d
        self.M = self.M[::-1]
        self.threshold = 1e-3

        self.is_2d_grid = self.qubit_map and isinstance(
            next(iter(self.qubit_map)), (cirq.GridQid, cirq.GridQubit)
        )

        if self.is_2d_grid:
            self.num_rows = max([qubit.row for qubit in qubit_map.keys()]) + 1
        else:
            self.num_rows = 1

    def __str__(self) -> str:
        return str(self.M)

    def _value_equality_values_(self) -> Any:
        return self.qubit_map, self.M, self.threshold

    def copy(self) -> 'MPSState':
        state = MPSState(self.qubit_map)
        state.M = [x.copy() for x in self.M]
        state.threshold = self.threshold
        return state

    def _sum_up(self, skip_tracing_out_for_qubits=None):
        row = -1
        for i in range(len(self.M)):
            row_i = list(self.qubit_map.keys())[i].row if self.is_2d_grid else 0

            if row != row_i:  # New row:
                if row == -1:  # First row
                    M = np.ones((1, 1, 1))
                else:
                    # We should have summed over all the column indices, thus they should be one.
                    assert Mi.shape[0] == 1
                    assert Mi.shape[1] == 1

                    Mi = Mi[0, 0, :, :, :]

                    M = np.einsum('mni,npj->mpij', M, Mi)
                    M = M.reshape(M.shape[0], M.shape[1], np.prod(M.shape[2:4]))

                Mi = np.ones((1, 1, 1, 1, 1))
                row = row_i

            skip_tracing_out = not skip_tracing_out_for_qubits or i in skip_tracing_out_for_qubits

            if skip_tracing_out:
                Mi = np.einsum('mnopi,nqrsj->mqorpsij', Mi, self.M[i])
                Mi = Mi.reshape(
                    Mi.shape[0],
                    Mi.shape[1],
                    Mi.shape[2] * Mi.shape[3],
                    Mi.shape[4] * Mi.shape[5],
                    Mi.shape[6] * Mi.shape[7],
                )
            else:
                Mi = np.einsum('mnopi,nqrsj->mqorpsi', Mi, self.M[i])
                Mi = Mi.reshape(
                    Mi.shape[0],
                    Mi.shape[1],
                    Mi.shape[2] * Mi.shape[3],
                    Mi.shape[4] * Mi.shape[5],
                    Mi.shape[6],
                )

        # We should have summed over all the column indices, thus they should be one.
        assert Mi.shape[0] == 1
        assert Mi.shape[1] == 1

        Mi = Mi[0, 0, :, :, :]

        M = np.einsum('mni,npj->mpij', M, Mi)
        M = M.reshape(M.shape[0], M.shape[1], M.shape[2] * M.shape[3])

        # We should have summed over all the row indices, thus they should be
        # one.
        assert M.shape[0] == 1
        assert M.shape[1] == 1
        return M[0, 0, :]

    def state_vector(self):
        return self._sum_up()

    def to_numpy(self) -> np.ndarray:
        return self.state_vector()

    def apply_unitary(self, op: 'cirq.Operation'):
        U = protocols.unitary(op).reshape([qubit.dimension for qubit in op.qubits] * 2)

        if len(op.qubits) == 1:
            n = self.qubit_map[op.qubits[0]]
            self.M[n] = np.einsum('ij,mnopj->mnopi', U, self.M[n])
        elif len(op.qubits) == 2:
            idx = [self.qubit_map[qubit] for qubit in op.qubits]
            if self.is_2d_grid:
                casted_op_qubits = [
                    cast(cirq.GridQid, qubit)
                    if isinstance(qubit, cirq.GridQid)
                    else cast(cirq.GridQubit, qubit)
                    for qubit in op.qubits
                ]

                if casted_op_qubits[0].row == casted_op_qubits[1].row:
                    if abs(casted_op_qubits[0].col - casted_op_qubits[1].col) != 1:
                        raise ValueError('qubits on same row but not one column appart')
                    same_row = True
                elif casted_op_qubits[0].col == casted_op_qubits[1].col:
                    if abs(casted_op_qubits[0].row - casted_op_qubits[1].row) != 1:
                        raise ValueError('qubits on same column but not one row appart')
                    same_row = False
                else:
                    raise ValueError('qubits neither on same row nor on same column')
            else:
                if abs(idx[0] - idx[1]) != 1:
                    raise ValueError('Can only handle continguous qubits')
                same_row = True
            if idx[0] < idx[1]:
                n, p = idx
            else:
                p, n = idx
                U = np.swapaxes(np.swapaxes(U, 0, 1), 2, 3)

            if same_row:
                T = np.einsum('klij,mnopi,nqrsj->mopkqrsl', U, self.M[n], self.M[p])
            else:
                T = np.einsum('klij,mnopi,qrpsj->mnokqrsl', U, self.M[n], self.M[p])
            X, S, Y = np.linalg.svd(T.reshape([np.prod(T.shape[0:4]), np.prod(T.shape[4:8])]))
            X = X.reshape(T.shape[0:4] + (-1,))
            Y = Y.reshape((-1,) + T.shape[4:8])

            S = np.asarray([math.sqrt(x) for x in S])

            nkeep = 0
            for i in range(S.shape[0]):
                if S[i] >= S[0] * self.threshold:
                    nkeep = i + 1

            X = X[:, :, :, :, :nkeep]
            S = np.diag(S[:nkeep])
            Y = Y[:nkeep, :, :, :, :]

            if same_row:
                self.M[n] = np.einsum('mopky,yn->mnopk', X, S)
                self.M[p] = np.einsum('yn,yqrsl->nqrsl', S, Y)
            else:
                self.M[n] = np.einsum('mnoky,yp->mnopk', X, S)
                self.M[p] = np.einsum('yp,yqrsl->qrpsl', S, Y)
        else:
            raise ValueError('Can only handle 1 and 2 qubit operations')

    def perform_measurement(
        self, qubits: Sequence[ops.Qid], prng: np.random.RandomState, collapse_state_vector=True
    ) -> List[int]:
        results: List[int] = []

        if collapse_state_vector:
            state = self
        else:
            state = self.copy()

        qid_shape = [qubit.dimension for qubit in qubits]
        skip_tracing_out_for_qubits = {state.qubit_map[qubit] for qubit in qubits}

        M = state._sum_up(skip_tracing_out_for_qubits=skip_tracing_out_for_qubits)

        for i, qubit in enumerate(qubits):
            # Trace out other qubits
            trace_out_idx = [j for j in range(len(qubits)) if j != i]
            M_traced_out = np.sum(M.reshape(qid_shape), axis=tuple(trace_out_idx))
            probs = [abs(x) ** 2 for x in M_traced_out]

            # Because the computation is approximate, the probabilities do not
            # necessarily add up to 1.0, and thus we re-normalize them.
            norm_probs = [x / sum(probs) for x in probs]

            d = qubit.dimension
            result: int = int(prng.choice(d, p=norm_probs))

            renormalizer = np.zeros((d, d))
            renormalizer[result][result] = 1.0 / math.sqrt(probs[result])

            n = state.qubit_map[qubit]
            state.M[n] = np.einsum('ij,mnopj->mnopi', renormalizer, state.M[n])

            collapser = np.ones(1)
            for j in range(len(qubits)):
                if j == i:
                    collapser = np.kron(collapser, renormalizer)
                else:
                    collapser = np.kron(collapser, np.eye(qid_shape[i]))

            M = np.einsum('ij,j->i', collapser, M)

            results.append(result)

        return results
