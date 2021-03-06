
import tensorflow as tf

from ..util import *
from ..args import ACTIVATION_FNS

def memory_cell(args, features, in_memory_state, in_data_read, in_control_state):

	with tf.name_scope("memory_cell"):

		memory_shape = [features["d_batch_size"], args["memory_width"]]
		in_memory_state = dynamic_assert_shape(in_memory_state, memory_shape)
		
		in_all = tf.concat([
			in_memory_state, 
			in_data_read
		], -1)

		forget_act = ACTIVATION_FNS[args["memory_forget_activation"]]
		act = ACTIVATION_FNS[args["memory_activation"]]

		new_memory_state = in_all
		for i in range(args["memory_transform_layers"]):
			new_memory_state = tf.layers.dense(new_memory_state, args["memory_width"], activation=act)

		# We can run this network without a control cell
		if in_control_state is not None:
			forget_scalar = tf.layers.dense(in_control_state, 1, activation=forget_act)
		else:
			forget_scalar = tf.layers.dense(in_all, 1, activation=forget_act)
	
		out_memory_state = (new_memory_state * forget_scalar) + (in_memory_state * (1-forget_scalar))
		out_memory_state = dynamic_assert_shape(out_memory_state, memory_shape)
		return out_memory_state, forget_scalar