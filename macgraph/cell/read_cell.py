
import tensorflow as tf

from ..util import *
from ..attention import *
from ..input import UNK_ID
from ..minception import *
from ..args import ACTIVATION_FNS

# TODO: Make indicator row data be special token

def read_from_table(args, features, in_signal, noun, table, width, table_len=None, table_max_len=None):

	if args["read_indicator_cols"] > 0:
		ind_col = tf.get_variable(f"{noun}_indicator_col", [1, 1, args["read_indicator_cols"]])
		ind_col = tf.tile(ind_col, [features["d_batch_size"], tf.shape(table)[1], 1])
		table = tf.concat([table, ind_col], axis=2)
		width += args["read_indicator_cols"]

	# query = tf.layers.dense(in_signal, width, activation=tf.nn.tanh)
	query = tf.layers.dense(in_signal, width)

	output, score = attention(table, query,
		word_size=width, 
		table_len=table_len,
		table_max_len=table_max_len,
	)

	output = dynamic_assert_shape(output, [features["d_batch_size"], width])
	return output, score, table


def read_from_table_with_embedding(args, features, vocab_embedding, in_signal, noun):
	"""Perform attention based read from table

	Will transform table into vocab embedding space
	
	@returns read_data
	"""

	with tf.name_scope(f"read_from_{noun}"):

		# --------------------------------------------------------------------------
		# Constants and validations
		# --------------------------------------------------------------------------

		table = features[f"{noun}s"]
		table_len = features[f"{noun}s_len"]

		width = args[f"{noun}_width"]
		full_width = width * args["embed_width"]

		d_len = tf.shape(table)[1]
		assert table.shape[-1] == width


		# --------------------------------------------------------------------------
		# Extend table if desired
		# --------------------------------------------------------------------------

		if args["read_indicator_rows"] > 0:
			# Add a trainable row to the table
			ind_row_shape = [features["d_batch_size"], args["read_indicator_rows"], width]
			ind_row = tf.fill(ind_row_shape, tf.cast(UNK_ID, table.dtype))
			table = tf.concat([table, ind_row], axis=1)
			table_len += args["read_indicator_rows"]
			d_len += args["read_indicator_rows"]

		# --------------------------------------------------------------------------
		# Embed graph tokens
		# --------------------------------------------------------------------------
		
		emb_kb = tf.nn.embedding_lookup(vocab_embedding, table)
		emb_kb = dynamic_assert_shape(emb_kb, 
			[features["d_batch_size"], d_len, width, args["embed_width"]])

		emb_kb = tf.reshape(emb_kb, [-1, d_len, full_width])
		emb_kb = dynamic_assert_shape(emb_kb, 
			[features["d_batch_size"], d_len, full_width])

		# --------------------------------------------------------------------------
		# Read
		# --------------------------------------------------------------------------

		return read_from_table(args, features, 
			in_signal, 
			noun,
			emb_kb, 
			width=full_width, 
			table_len=table_len, 
			table_max_len=args[f"{noun}_max_len"])



def read_cell(args, features, vocab_embedding, 
	in_memory_state, in_control_state, in_data_stack, in_question_tokens, in_question_state):
	"""
	A read cell

	@returns read_data

	"""


	with tf.name_scope("read_cell"):

		# --------------------------------------------------------------------------
		# Read data
		# --------------------------------------------------------------------------

		in_signal = []

		if in_memory_state is not None and args["use_memory_cell"]:
			in_signal.append(in_memory_state)

		# We may run the network with no control cell
		if in_control_state is not None and args["use_control_cell"]:
			in_signal.append(in_control_state)

		if args["read_from_question"]:
			in_signal.append(in_question_tokens[:,2])
			in_signal.append(in_question_tokens[:,6])

		if args["use_read_question_state"] or len(in_signal)==0:
			in_signal.append(in_question_state)

		in_signal = tf.concat(in_signal, -1)

		reads = []
		tap_attns = []
		tap_table = None

		taps = {}
		read_word_width = 0

		read_datas = []

		for j in range(args["read_heads"]):
			for i in ["kb_node", "kb_edge"]:
				if args[f"use_{i}"]:
					read, attn, table = read_from_table_with_embedding(
						args, 
						features, 
						vocab_embedding, 
						in_signal, 
						noun=i
					)

					read_word_width += args[i+"_width"]
					reads.append(read)
					taps[i+"_attn"] = attn

			if args["use_data_stack"]:
				# Attentional read
				read, attn, table = read_from_table(args, 
					features, in_signal, 
					noun="data_stack", 
					table=in_data_stack, 
					width=args["data_stack_width"] * args["embed_width"])

				read_word_width += args["data_stack_width"]
				reads.append(read)
				reads.append(in_data_stack[:,0,:]) # Head read


			read_data = tf.concat(reads, -1)

			if args[f"use_read_extract"]:
				read_words = tf.reshape(read_data, [features["d_batch_size"], read_word_width, args["embed_width"]])
				word_query = tf.layers.dense(in_signal, read_word_width)
				word_query = tf.nn.softmax(word_query, axis=1)
				read_data = read_words * tf.expand_dims(word_query, -1)
				read_data = tf.reduce_sum(read_data, axis=1)
				taps["read_word_query"] = word_query

			read_datas.append(read_data)
		
		

		# --------------------------------------------------------------------------
		# Prepare and shape results
		# --------------------------------------------------------------------------
		
		out_data = tf.concat([*read_datas, in_signal], -1)
		
		for i in range(args["read_layers"]):
			out_data = tf.layers.dense(out_data, args["read_width"])
			out_data = ACTIVATION_FNS[args["read_activation"]](out_data)
			
			if args["read_dropout"] > 0:
				out_data = tf.nn.dropout(out_data, 1.0-args["read_dropout"])

		# read_fn_switch = tf.layers.dense(in_signal, args["read_width"], tf.sigmoid)
		# out_data = out_data * read_fn_switch

		return out_data, taps




