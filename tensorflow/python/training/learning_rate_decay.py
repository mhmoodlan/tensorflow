# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Various learning rate decay functions."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math

from tensorflow.python.eager import context
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import random_ops
from tensorflow.python.util.tf_export import tf_export


@tf_export("train.cyclic_learning_rate")
def cyclic_learning_rate(global_step,
                         learning_rate=0.01,
                         max_lr=0.1,
                         step_size=20.,
                         gamma=0.99994,
                         mode='triangular',
                         name=None):
  """Applies cyclic learning rate (CLR).
     From the paper:
     Smith, Leslie N. "Cyclical learning
     rates for training neural networks." 2017.
     [https://arxiv.org/pdf/1506.01186.pdf]

     This method lets the learning rate cyclically
     vary between reasonable boundary values
     achieving improved classification accuracy and
     often in fewer iterations.

     This code varies the learning rate linearly between the
     minimum (learning_rate) and the maximum (max_lr).

     It returns the cyclic learning rate. It is computed as:

      ```python

      cycle = floor( 1 + global_step /
        ( 2 * step_size ) )
      x = abs( global_step / step_size – 2 * cycle + 1 )
      clr = learning_rate +
        ( max_lr – learning_rate ) * max( 0 , 1 - x )

      ```
      Polices:
        'triangular':
          Default, linearly increasing then linearly decreasing the
          learning rate at each cycle.

        'triangular2':
          The same as the triangular policy except the learning
          rate difference is cut in half at the end of each cycle.
          This means the learning rate difference drops after each cycle.

        'exp_range':
          The learning rate varies between the minimum and maximum
          boundaries and each boundary value declines by an exponential
          factor of: gamma^global_step.

      Example: 'triangular2' mode cyclic learning rate.
        '''python
        ...
        global_step = tf.Variable(0, trainable=False)
        optimizer = tf.train.AdamOptimizer(learning_rate=
          clr.cyclic_learning_rate(global_step=global_step, mode='triangular2'))
        train_op = optimizer.minimize(loss_op, global_step=global_step)
        ...

        with tf.Session() as sess:
            sess.run(init)
            for step in range(1, num_steps+1):
              assign_op = global_step.assign(step)
              sess.run(assign_op)
        ...

        '''

      Args:
        global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
          Global step to use for the cyclic computation.  Must not be negative.
        learning_rate: A scalar `float32` or `float64` `Tensor` or a
        Python number.  The initial learning rate which is the lower bound
          of the cycle (default = 0.1).
        max_lr:  A scalar. The maximum learning rate boundary.
        step_size: A scalar. The number of iterations in half a cycle.
          The paper suggests step_size = 2-8 x training iterations in epoch.
        gamma: constant in 'exp_range' mode:
          gamma**(global_step)
        mode: one of {triangular, triangular2, exp_range}.
            Default 'triangular'.
            Values correspond to policies detailed above.
        name: String.  Optional name of the operation.  Defaults to
          'CyclicLearningRate'.

      Returns:
        A scalar `Tensor` of the same type as `learning_rate`.  The cyclic
        learning rate.
      Raises:
        ValueError: if `global_step` is not supplied.

     @compatibility(eager)
      When eager execution is enabled, this function returns
      a function which in turn returns the decayed learning
      rate Tensor. This can be useful for changing the learning
      rate value across different invocations of optimizer functions.
      @end_compatibility
  """

  if global_step is None:
    raise ValueError("global_step is required for cyclic_learning_rate.")

  with ops.name_scope(name, "CyclicLearningRate",
                      [learning_rate, global_step]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    global_step = math_ops.cast(global_step, dtype)
    step_size = math_ops.cast(step_size, dtype)

    def cyclic_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      # computing: cycle = floor( 1 + global_step / ( 2 * step_size ) )
      double_step = math_ops.multiply(2., step_size)
      global_div_double_step = math_ops.divide(global_step, double_step)
      cycle = math_ops.floor(math_ops.add(1., global_div_double_step))

      # computing: x = abs( global_step / step_size – 2 * cycle + 1 )
      double_cycle = math_ops.multiply(2., cycle)
      global_div_step = math_ops.divide(global_step, step_size)
      tmp = math_ops.subtract(global_div_step, double_cycle)
      x = math_ops.abs(math_ops.add(1., tmp))

      # computing: clr = learning_rate + ( max_lr – learning_rate ) * max( 0, 1 - x )
      a1 = math_ops.maximum(0., math_ops.subtract(1., x))
      a2 = math_ops.subtract(max_lr, learning_rate)
      clr = math_ops.multiply(a1, a2)

      if mode == 'triangular2':
        clr = math_ops.divide(clr, math_ops.cast(math_ops.pow(2, math_ops.cast(
            cycle-1, tf.int32)), tf.float32))
      if mode == 'exp_range':
        clr = math_ops.multiply(math_ops.pow(gamma, global_step), clr)

      return math_ops.add(clr, learning_rate, name=name)

    if not context.executing_eagerly():
      cyclic_lr = cyclic_lr()

    return cyclic_lr


@tf_export("train.exponential_decay")
def exponential_decay(learning_rate,
                      global_step,
                      decay_steps,
                      decay_rate,
                      staircase=False,
                      name=None):
  """Applies exponential decay to the learning rate.

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies an exponential decay function
  to a provided initial learning rate.  It requires a `global_step` value to
  compute the decayed learning rate.  You can just pass a TensorFlow variable
  that you increment at each training step.

  The function returns the decayed learning rate.  It is computed as:

  ```python
  decayed_learning_rate = learning_rate *
                          decay_rate ^ (global_step / decay_steps)
  ```

  If the argument `staircase` is `True`, then `global_step / decay_steps` is an
  integer division and the decayed learning rate follows a staircase function.

  Example: decay every 100000 steps with a base of 0.96:

  ```python
  ...
  global_step = tf.Variable(0, trainable=False)
  starter_learning_rate = 0.1
  learning_rate = tf.train.exponential_decay(starter_learning_rate, global_step,
                                             100000, 0.96, staircase=True)
  # Passing global_step to minimize() will increment it at each step.
  learning_step = (
      tf.train.GradientDescentOptimizer(learning_rate)
      .minimize(...my loss..., global_step=global_step)
  )
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.  Must not be negative.
    decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Must be positive.  See the decay computation above.
    decay_rate: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The decay rate.
    staircase: Boolean.  If `True` decay the learning rate at discrete intervals
    name: String.  Optional name of the operation.  Defaults to
      'ExponentialDecay'.

  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.

  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("global_step is required for exponential_decay.")
  with ops.name_scope(
      name, "ExponentialDecay",
      [learning_rate, global_step, decay_steps, decay_rate]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    decay_steps = math_ops.cast(decay_steps, dtype)
    decay_rate = math_ops.cast(decay_rate, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      p = global_step_recomp / decay_steps
      if staircase:
        p = math_ops.floor(p)
      return math_ops.multiply(
          learning_rate, math_ops.pow(decay_rate, p), name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.piecewise_constant")
def piecewise_constant(x, boundaries, values, name=None):
  """Piecewise constant from boundaries and interval values.

  Example: use a learning rate that's 1.0 for the first 100001 steps, 0.5
    for the next 10000 steps, and 0.1 for any additional steps.

  ```python
  global_step = tf.Variable(0, trainable=False)
  boundaries = [100000, 110000]
  values = [1.0, 0.5, 0.1]
  learning_rate = tf.train.piecewise_constant(global_step, boundaries, values)

  # Later, whenever we perform an optimization step, we increment global_step.
  ```

  Args:
    x: A 0-D scalar `Tensor`. Must be one of the following types: `float32`,
      `float64`, `uint8`, `int8`, `int16`, `int32`, `int64`.
    boundaries: A list of `Tensor`s or `int`s or `float`s with strictly
      increasing entries, and with all elements having the same type as `x`.
    values: A list of `Tensor`s or `float`s or `int`s that specifies the values
      for the intervals defined by `boundaries`. It should have one more element
      than `boundaries`, and all elements should have the same type.
    name: A string. Optional name of the operation. Defaults to
      'PiecewiseConstant'.

  Returns:
    A 0-D Tensor. Its value is `values[0]` when `x <= boundaries[0]`,
    `values[1]` when `x > boundaries[0]` and `x <= boundaries[1]`, ...,
    and values[-1] when `x > boundaries[-1]`.

  Raises:
    ValueError: if types of `x` and `boundaries` do not match, or types of all
        `values` do not match or
        the number of elements in the lists does not match.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if len(boundaries) != len(values) - 1:
    raise ValueError(
        "The length of boundaries should be 1 less than the length of values")
  with ops.name_scope(name, "PiecewiseConstant",
                      [x, boundaries, values, name]) as name:
    boundaries = ops.convert_n_to_tensor(boundaries)
    values = ops.convert_n_to_tensor(values)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      x_recomp = ops.convert_to_tensor(x)
      # Avoid explicit conversion to x's dtype. This could result in faulty
      # comparisons, for example if floats are converted to integers.
      for i, b in enumerate(boundaries):
        if b.dtype.base_dtype != x_recomp.dtype.base_dtype:
          # We can promote int32 boundaries to int64 without loss of precision.
          # This covers the most common case where the user passes in boundaries
          # as an array of Python integers.
          if (b.dtype.base_dtype == dtypes.int32 and
              x_recomp.dtype.base_dtype == dtypes.int64):
            b = math_ops.cast(b, x_recomp.dtype.base_dtype)
            boundaries[i] = b
          else:
            raise ValueError(
                "Boundaries (%s) must have the same dtype as x (%s)." %
                (b.dtype.base_dtype, x_recomp.dtype.base_dtype))
      # TODO(rdipietro): Ensure that boundaries' elements strictly increases.
      for v in values[1:]:
        if v.dtype.base_dtype != values[0].dtype.base_dtype:
          raise ValueError(
              "Values must have elements all with the same dtype (%s vs %s)." %
              (values[0].dtype.base_dtype, v.dtype.base_dtype))
      pred_fn_pairs = []
      pred_fn_pairs.append((x_recomp <= boundaries[0], lambda: values[0]))
      pred_fn_pairs.append((x_recomp > boundaries[-1], lambda: values[-1]))
      for low, high, v in zip(boundaries[:-1], boundaries[1:], values[1:-1]):
        # Need to bind v here; can do this with lambda v=v: ...
        pred = (x_recomp > low) & (x_recomp <= high)
        pred_fn_pairs.append((pred, lambda v=v: v))

      # The default isn't needed here because our conditions are mutually
      # exclusive and exhaustive, but tf.case requires it.
      default = lambda: values[0]
      return control_flow_ops.case(pred_fn_pairs, default, exclusive=True)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.polynomial_decay")
def polynomial_decay(learning_rate,
                     global_step,
                     decay_steps,
                     end_learning_rate=0.0001,
                     power=1.0,
                     cycle=False,
                     name=None):
  """Applies a polynomial decay to the learning rate.

  It is commonly observed that a monotonically decreasing learning rate, whose
  degree of change is carefully chosen, results in a better performing model.
  This function applies a polynomial decay function to a provided initial
  `learning_rate` to reach an `end_learning_rate` in the given `decay_steps`.

  It requires a `global_step` value to compute the decayed learning rate.  You
  can just pass a TensorFlow variable that you increment at each training step.

  The function returns the decayed learning rate.  It is computed as:

  ```python
  global_step = min(global_step, decay_steps)
  decayed_learning_rate = (learning_rate - end_learning_rate) *
                          (1 - global_step / decay_steps) ^ (power) +
                          end_learning_rate

  ```

  If `cycle` is True then a multiple of `decay_steps` is used, the first one
  that is bigger than `global_steps`.

  ```python
  decay_steps = decay_steps * ceil(global_step / decay_steps)
  decayed_learning_rate = (learning_rate - end_learning_rate) *
                          (1 - global_step / decay_steps) ^ (power) +
                          end_learning_rate

  ```

  Example: decay from 0.1 to 0.01 in 10000 steps using sqrt (i.e. power=0.5):

  ```python
  ...
  global_step = tf.Variable(0, trainable=False)
  starter_learning_rate = 0.1
  end_learning_rate = 0.01
  decay_steps = 10000
  learning_rate = tf.train.polynomial_decay(starter_learning_rate, global_step,
                                            decay_steps, end_learning_rate,
                                            power=0.5)
  # Passing global_step to minimize() will increment it at each step.
  learning_step = (
      tf.train.GradientDescentOptimizer(learning_rate)
      .minimize(...my loss..., global_step=global_step)
  )
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.  Must not be negative.
    decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Must be positive.  See the decay computation above.
    end_learning_rate: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The minimal end learning rate.
    power: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The power of the polynomial. Defaults to linear, 1.0.
    cycle: A boolean, whether or not it should cycle beyond decay_steps.
    name: String.  Optional name of the operation. Defaults to
      'PolynomialDecay'.

  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.

  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("global_step is required for polynomial_decay.")
  with ops.name_scope(
      name, "PolynomialDecay",
      [learning_rate, global_step, decay_steps, end_learning_rate, power
      ]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    end_learning_rate = math_ops.cast(end_learning_rate, dtype)
    power = math_ops.cast(power, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      decay_steps_recomp = math_ops.cast(decay_steps, dtype)
      if cycle:
        # Find the first multiple of decay_steps that is bigger than
        # global_step. If global_step is zero set the multiplier to 1
        multiplier = control_flow_ops.cond(
            math_ops.equal(global_step_recomp, 0), lambda: 1.0,
            lambda: math_ops.ceil(global_step_recomp / decay_steps))
        decay_steps_recomp = math_ops.multiply(decay_steps_recomp, multiplier)
      else:
        # Make sure that the global_step used is not bigger than decay_steps.
        global_step_recomp = math_ops.minimum(global_step_recomp, decay_steps)

      p = math_ops.div(global_step_recomp, decay_steps_recomp)
      return math_ops.add(
          math_ops.multiply(learning_rate - end_learning_rate,
                            math_ops.pow(1 - p, power)),
          end_learning_rate,
          name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.natural_exp_decay")
def natural_exp_decay(learning_rate,
                      global_step,
                      decay_steps,
                      decay_rate,
                      staircase=False,
                      name=None):
  """Applies natural exponential decay to the initial learning rate.

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies an exponential decay function
  to a provided initial learning rate.  It requires an `global_step` value to
  compute the decayed learning rate.  You can just pass a TensorFlow variable
  that you increment at each training step.

  The function returns the decayed learning rate.  It is computed as:

  ```python
  decayed_learning_rate = learning_rate * exp(-decay_rate * global_step)
  ```

  Example: decay exponentially with a base of 0.96:

  ```python
  ...
  global_step = tf.Variable(0, trainable=False)
  learning_rate = 0.1
  k = 0.5
  learning_rate = tf.train.exponential_time_decay(learning_rate, global_step, k)

  # Passing global_step to minimize() will increment it at each step.
  learning_step = (
      tf.train.GradientDescentOptimizer(learning_rate)
      .minimize(...my loss..., global_step=global_step)
  )
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The initial learning rate.
    global_step: A Python number.
      Global step to use for the decay computation.  Must not be negative.
    decay_steps: How often to apply decay.
    decay_rate: A Python number.  The decay rate.
    staircase: Whether to apply decay in a discrete staircase, as opposed to
      continuous, fashion.
    name: String.  Optional name of the operation.  Defaults to
      'ExponentialTimeDecay'.

  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.

  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("global_step is required for natural_exp_decay.")
  with ops.name_scope(name, "NaturalExpDecay",
                      [learning_rate, global_step, decay_rate]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    decay_steps = math_ops.cast(decay_steps, dtype)
    decay_rate = math_ops.cast(decay_rate, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      p = global_step_recomp / decay_steps
      if staircase:
        p = math_ops.floor(p)
      exponent = math_ops.exp(
          math_ops.multiply(math_ops.negative(decay_rate), p))
      return math_ops.multiply(learning_rate, exponent, name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.inverse_time_decay")
def inverse_time_decay(learning_rate,
                       global_step,
                       decay_steps,
                       decay_rate,
                       staircase=False,
                       name=None):
  """Applies inverse time decay to the initial learning rate.

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies an inverse decay function
  to a provided initial learning rate.  It requires an `global_step` value to
  compute the decayed learning rate.  You can just pass a TensorFlow variable
  that you increment at each training step.

  The function returns the decayed learning rate.  It is computed as:

  ```python
  decayed_learning_rate = learning_rate / (1 + decay_rate * global_step /
  decay_step)
  ```

  or, if `staircase` is `True`, as:

  ```python
  decayed_learning_rate = learning_rate / (1 + decay_rate * floor(global_step /
  decay_step))
  ```

  Example: decay 1/t with a rate of 0.5:

  ```python
  ...
  global_step = tf.Variable(0, trainable=False)
  learning_rate = 0.1
  decay_steps = 1.0
  decay_rate = 0.5
  learning_rate = tf.train.inverse_time_decay(learning_rate, global_step,
  decay_steps, decay_rate)

  # Passing global_step to minimize() will increment it at each step.
  learning_step = (
      tf.train.GradientDescentOptimizer(learning_rate)
      .minimize(...my loss..., global_step=global_step)
  )
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` `Tensor` or a
      Python number.  The initial learning rate.
    global_step: A Python number.
      Global step to use for the decay computation.  Must not be negative.
    decay_steps: How often to apply decay.
    decay_rate: A Python number.  The decay rate.
    staircase: Whether to apply decay in a discrete staircase, as opposed to
      continuous, fashion.
    name: String.  Optional name of the operation.  Defaults to
      'InverseTimeDecay'.

  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.

  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("global_step is required for inverse_time_decay.")
  with ops.name_scope(name, "InverseTimeDecay",
                      [learning_rate, global_step, decay_rate]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    decay_steps = math_ops.cast(decay_steps, dtype)
    decay_rate = math_ops.cast(decay_rate, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      p = global_step_recomp / decay_steps
      if staircase:
        p = math_ops.floor(p)
      const = math_ops.cast(constant_op.constant(1), dtype)
      denom = math_ops.add(const, math_ops.multiply(decay_rate, p))
      return math_ops.div(learning_rate, denom, name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.cosine_decay")
def cosine_decay(learning_rate, global_step, decay_steps, alpha=0.0, name=None):
  """Applies cosine decay to the learning rate.

  See [Loshchilov & Hutter, ICLR2016], SGDR: Stochastic Gradient Descent
  with Warm Restarts. https://arxiv.org/abs/1608.03983

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies a cosine decay function
  to a provided initial learning rate.  It requires a `global_step` value to
  compute the decayed learning rate.  You can just pass a TensorFlow variable
  that you increment at each training step.

  The function returns the decayed learning rate.  It is computed as:
  ```python
  global_step = min(global_step, decay_steps)
  cosine_decay = 0.5 * (1 + cos(pi * global_step / decay_steps))
  decayed = (1 - alpha) * cosine_decay + alpha
  decayed_learning_rate = learning_rate * decayed
  ```

  Example usage:
  ```python
  decay_steps = 1000
  lr_decayed = cosine_decay(learning_rate, global_step, decay_steps)
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` Tensor or a Python number.
      The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.
    decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Number of steps to decay over.
    alpha: A scalar `float32` or `float64` Tensor or a Python number.
      Minimum learning rate value as a fraction of learning_rate.
    name: String. Optional name of the operation.  Defaults to 'CosineDecay'.
  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.
  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("cosine decay requires global_step")
  with ops.name_scope(name, "CosineDecay",
                      [learning_rate, global_step]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    decay_steps = math_ops.cast(decay_steps, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      global_step_recomp = math_ops.minimum(global_step_recomp, decay_steps)
      completed_fraction = global_step_recomp / decay_steps
      cosine_decayed = 0.5 * (1.0 + math_ops.cos(
          constant_op.constant(math.pi) * completed_fraction))

      decayed = (1 - alpha) * cosine_decayed + alpha
      return math_ops.multiply(learning_rate, decayed)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.cosine_decay_restarts")
def cosine_decay_restarts(learning_rate,
                          global_step,
                          first_decay_steps,
                          t_mul=2.0,
                          m_mul=1.0,
                          alpha=0.0,
                          name=None):
  """Applies cosine decay with restarts to the learning rate.

  See [Loshchilov & Hutter, ICLR2016], SGDR: Stochastic Gradient Descent
  with Warm Restarts. https://arxiv.org/abs/1608.03983

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies a cosine decay function with
  restarts to a provided initial learning rate.  It requires a `global_step`
  value to compute the decayed learning rate.  You can just pass a TensorFlow
  variable that you increment at each training step.

  The function returns the decayed learning rate while taking into account
  possible warm restarts. The learning rate multiplier first decays
  from 1 to `alpha` for `first_decay_steps` steps. Then, a warm
  restart is performed. Each new warm restart runs for `t_mul` times more steps
  and with `m_mul` times smaller initial learning rate.

  Example usage:
  ```python
  first_decay_steps = 1000
  lr_decayed = cosine_decay_restarts(learning_rate, global_step,
                                     first_decay_steps)
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` Tensor or a Python number.
      The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.
    first_decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Number of steps to decay over.
    t_mul: A scalar `float32` or `float64` `Tensor` or a Python number.
      Used to derive the number of iterations in the i-th period
    m_mul: A scalar `float32` or `float64` `Tensor` or a Python number.
      Used to derive the initial learning rate of the i-th period:
    alpha: A scalar `float32` or `float64` Tensor or a Python number.
      Minimum learning rate value as a fraction of the learning_rate.
    name: String. Optional name of the operation.  Defaults to 'SGDRDecay'.
  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.
  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("cosine decay restarts requires global_step")
  with ops.name_scope(name, "SGDRDecay", [learning_rate, global_step]) as name:
    learning_rate = ops.convert_to_tensor(
        learning_rate, name="initial_learning_rate")
    dtype = learning_rate.dtype
    first_decay_steps = math_ops.cast(first_decay_steps, dtype)
    alpha = math_ops.cast(alpha, dtype)
    t_mul = math_ops.cast(t_mul, dtype)
    m_mul = math_ops.cast(m_mul, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      completed_fraction = global_step_recomp / first_decay_steps

      def compute_step(completed_fraction, geometric=False):
        """Helper for `cond` operation."""
        if geometric:
          i_restart = math_ops.floor(
              math_ops.log(1.0 - completed_fraction * (1.0 - t_mul)) /
              math_ops.log(t_mul))

          sum_r = (1.0 - t_mul**i_restart) / (1.0 - t_mul)
          completed_fraction = (completed_fraction - sum_r) / t_mul**i_restart

        else:
          i_restart = math_ops.floor(completed_fraction)
          completed_fraction -= i_restart

        return i_restart, completed_fraction

      i_restart, completed_fraction = control_flow_ops.cond(
          math_ops.equal(t_mul, 1.0),
          lambda: compute_step(completed_fraction, geometric=False),
          lambda: compute_step(completed_fraction, geometric=True))

      m_fac = m_mul**i_restart
      cosine_decayed = 0.5 * m_fac * (1.0 + math_ops.cos(
          constant_op.constant(math.pi) * completed_fraction))
      decayed = (1 - alpha) * cosine_decayed + alpha

      return math_ops.multiply(learning_rate, decayed, name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.linear_cosine_decay")
def linear_cosine_decay(learning_rate,
                        global_step,
                        decay_steps,
                        num_periods=0.5,
                        alpha=0.0,
                        beta=0.001,
                        name=None):
  """Applies linear cosine decay to the learning rate.

  See [Bello et al., ICML2017] Neural Optimizer Search with RL.
  https://arxiv.org/abs/1709.07417

  For the idea of warm starts here controlled by `num_periods`,
  see [Loshchilov & Hutter, ICLR2016] SGDR: Stochastic Gradient Descent
  with Warm Restarts. https://arxiv.org/abs/1608.03983

  Note that linear cosine decay is more aggressive than cosine decay and
  larger initial learning rates can typically be used.

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies a linear cosine decay function
  to a provided initial learning rate.  It requires a `global_step` value to
  compute the decayed learning rate.  You can just pass a TensorFlow variable
  that you increment at each training step.

  The function returns the decayed learning rate.  It is computed as:
  ```python
  global_step = min(global_step, decay_steps)
  linear_decay = (decay_steps - global_step) / decay_steps)
  cosine_decay = 0.5 * (
      1 + cos(pi * 2 * num_periods * global_step / decay_steps))
  decayed = (alpha + linear_decay) * cosine_decay + beta
  decayed_learning_rate = learning_rate * decayed
  ```

  Example usage:
  ```python
  decay_steps = 1000
  lr_decayed = linear_cosine_decay(learning_rate, global_step, decay_steps)
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` Tensor or a Python number.
      The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.
    decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Number of steps to decay over.
    num_periods: Number of periods in the cosine part of the decay.
      See computation above.
    alpha: See computation above.
    beta: See computation above.
    name: String.  Optional name of the operation.  Defaults to
      'LinearCosineDecay'.
  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.
  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("linear cosine decay requires global_step")
  with ops.name_scope(name, "LinearCosineDecay",
                      [learning_rate, global_step]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    decay_steps = math_ops.cast(decay_steps, dtype)
    num_periods = math_ops.cast(num_periods, dtype)
    alpha = math_ops.cast(alpha, dtype)
    beta = math_ops.cast(beta, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      global_step_recomp = math_ops.minimum(global_step_recomp, decay_steps)
      linear_decayed = (decay_steps - global_step_recomp) / decay_steps
      completed_fraction = global_step_recomp / decay_steps
      fraction = 2.0 * num_periods * completed_fraction
      cosine_decayed = 0.5 * (
          1.0 + math_ops.cos(constant_op.constant(math.pi) * fraction))

      linear_cosine_decayed = (alpha + linear_decayed) * cosine_decayed + beta
      return math_ops.multiply(learning_rate, linear_cosine_decayed, name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr


@tf_export("train.noisy_linear_cosine_decay")
def noisy_linear_cosine_decay(learning_rate,
                              global_step,
                              decay_steps,
                              initial_variance=1.0,
                              variance_decay=0.55,
                              num_periods=0.5,
                              alpha=0.0,
                              beta=0.001,
                              name=None):
  """Applies noisy linear cosine decay to the learning rate.

  See [Bello et al., ICML2017] Neural Optimizer Search with RL.
  https://arxiv.org/abs/1709.07417

  For the idea of warm starts here controlled by `num_periods`,
  see [Loshchilov & Hutter, ICLR2016] SGDR: Stochastic Gradient Descent
  with Warm Restarts. https://arxiv.org/abs/1608.03983

  Note that linear cosine decay is more aggressive than cosine decay and
  larger initial learning rates can typically be used.

  When training a model, it is often recommended to lower the learning rate as
  the training progresses.  This function applies a noisy linear
  cosine decay function to a provided initial learning rate.
  It requires a `global_step` value to compute the decayed learning rate.
  You can just pass a TensorFlow variable that you increment at each
  training step.

  The function returns the decayed learning rate.  It is computed as:
  ```python
  global_step = min(global_step, decay_steps)
  linear_decay = (decay_steps - global_step) / decay_steps)
  cosine_decay = 0.5 * (
      1 + cos(pi * 2 * num_periods * global_step / decay_steps))
  decayed = (alpha + linear_decay + eps_t) * cosine_decay + beta
  decayed_learning_rate = learning_rate * decayed
  ```
  where eps_t is 0-centered gaussian noise with variance
  initial_variance / (1 + global_step) ** variance_decay

  Example usage:
  ```python
  decay_steps = 1000
  lr_decayed = noisy_linear_cosine_decay(
    learning_rate, global_step, decay_steps)
  ```

  Args:
    learning_rate: A scalar `float32` or `float64` Tensor or a Python number.
      The initial learning rate.
    global_step: A scalar `int32` or `int64` `Tensor` or a Python number.
      Global step to use for the decay computation.
    decay_steps: A scalar `int32` or `int64` `Tensor` or a Python number.
      Number of steps to decay over.
    initial_variance: initial variance for the noise. See computation above.
    variance_decay: decay for the noise's variance. See computation above.
    num_periods: Number of periods in the cosine part of the decay.
      See computation above.
    alpha: See computation above.
    beta: See computation above.
    name: String.  Optional name of the operation.  Defaults to
      'NoisyLinearCosineDecay'.
  Returns:
    A scalar `Tensor` of the same type as `learning_rate`.  The decayed
    learning rate.
  Raises:
    ValueError: if `global_step` is not supplied.

  @compatibility(eager)
  When eager execution is enabled, this function returns a function which in
  turn returns the decayed learning rate Tensor. This can be useful for changing
  the learning rate value across different invocations of optimizer functions.
  @end_compatibility
  """
  if global_step is None:
    raise ValueError("noisy linear cosine decay requires global_step")
  with ops.name_scope(name, "NoisyLinearCosineDecay",
                      [learning_rate, global_step]) as name:
    learning_rate = ops.convert_to_tensor(learning_rate, name="learning_rate")
    dtype = learning_rate.dtype
    decay_steps = math_ops.cast(decay_steps, dtype)
    initial_variance = math_ops.cast(initial_variance, dtype)
    variance_decay = math_ops.cast(variance_decay, dtype)
    num_periods = math_ops.cast(num_periods, dtype)
    alpha = math_ops.cast(alpha, dtype)
    beta = math_ops.cast(beta, dtype)

    def decayed_lr():
      """Helper to recompute learning rate; most helpful in eager-mode."""
      global_step_recomp = math_ops.cast(global_step, dtype)
      global_step_recomp = math_ops.minimum(global_step_recomp, decay_steps)
      linear_decayed = (decay_steps - global_step_recomp) / decay_steps
      variance = initial_variance / (
          math_ops.pow(1.0 + global_step_recomp, variance_decay))
      std = math_ops.sqrt(variance)
      noisy_linear_decayed = (
          linear_decayed + random_ops.random_normal(
              linear_decayed.shape, stddev=std))

      completed_fraction = global_step_recomp / decay_steps
      fraction = 2.0 * num_periods * completed_fraction
      cosine_decayed = 0.5 * (
          1.0 + math_ops.cos(constant_op.constant(math.pi) * fraction))
      noisy_linear_cosine_decayed = (
          (alpha + noisy_linear_decayed) * cosine_decayed + beta)

      return math_ops.multiply(
          learning_rate, noisy_linear_cosine_decayed, name=name)

    if not context.executing_eagerly():
      decayed_lr = decayed_lr()

    return decayed_lr
