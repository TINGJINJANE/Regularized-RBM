#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This script contains class SupervMixedRBM and a simple example of its
implementation.
"""

from __future__ import print_function

from util import tf_xavier_init, sample_bernoulli, sample_gaussian
import tensorflow as tf
import numpy as np
import sys

# TODO: comment this line in production environment
# tf.set_random_seed(1)

class SemiSupervRBM:
    """
    """

    def __init__(self,
                 n_y, # number of supervised (bernoulli) visible units
                 n_x, # number of unsupervised (gaussian) visible units
                 n_h, # number of bernoulli hidden units
                 alpha=0.1,
                 sample_visible=False,
                 learning_rate=0.01,
                 momentum=0.95,
                 xavier_const=1.0,
                 err_function='mse'):
        if not 0.0 <= momentum <= 1.0:
            raise ValueError('momentum should be in range [0, 1]')

        if err_function not in {'mse', 'cosine'}:
            raise ValueError('err_function should be either \'mse\' or \'cosine\'')

        # configurations
        self.n_y = n_y
        self.n_x = n_x
        self.n_h = n_h
        self.learning_rate  = learning_rate
        self.momentum       = momentum
        self.sample_visible = sample_visible
        self.alpha          = alpha

        # input parameters
        self.x = tf.placeholder(tf.float32, [None, self.n_x])
        self.y = tf.placeholder(tf.float32, [None, self.n_y])
        self.h = tf.placeholder(tf.float32, [None, self.n_h])

        # variables of semi-rbm
        self.y_w = tf.Variable(tf_xavier_init(self.n_y, self.n_h, const=xavier_const), dtype=tf.float32)
        self.x_w = tf.Variable(tf_xavier_init(self.n_x, self.n_h, const=xavier_const), dtype=tf.float32)
        self.y_b = tf.Variable(tf.zeros([self.n_y]), dtype=tf.float32)
        self.x_b = tf.Variable(tf.zeros([self.n_x]), dtype=tf.float32)
        self.h_b = tf.Variable(tf.zeros([self.n_h]), dtype=tf.float32)
        self.x_sigma = 1. # TODO: change fixed sigma to tensor variable

        # variables of weights updates
        self.delta_y_w = tf.Variable(tf.zeros([self.n_y, self.n_h]), dtype=tf.float32)
        self.delta_x_w = tf.Variable(tf.zeros([self.n_x, self.n_h]), dtype=tf.float32)
        self.delta_y_b = tf.Variable(tf.zeros([self.n_y]), dtype=tf.float32)
        self.delta_x_b = tf.Variable(tf.zeros([self.n_x]), dtype=tf.float32)
        self.delta_h_b = tf.Variable(tf.zeros([self.n_h]), dtype=tf.float32)

        self.update_weights  = None
        self.update_deltas   = None
        self.compute_hidden  = None
        self.compute_visible = None
        self.compute_visible_from_hidden = None

        self._initialize_vars()

        assert self.update_weights is not None
        assert self.update_deltas is not None
        assert self.compute_hidden is not None
        assert self.compute_visible is not None
        assert self.compute_visible_from_hidden is not None

        if err_function == 'cosine':
            x1_norm = tf.nn.l2_normalize(self.x, 1)
            x2_norm = tf.nn.l2_normalize(self.compute_visible, 1)
            cos_val = tf.reduce_mean(tf.reduce_sum(tf.mul(x1_norm, x2_norm), 1))
            self.compute_err = tf.acos(cos_val) / tf.constant(np.pi)
        else:
            self.compute_err = tf.reduce_mean(tf.square(self.x - self.compute_visible))

        # init all defined variables before training
        init = tf.global_variables_initializer()
        self.sess = tf.Session()
        self.sess.run(init)

    # def test(self):
    #     y = [[1,0,0], [0,1,0]]
    #     x = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.1, 0.2, 0.3, 0.4, 0.5],
    #          [0.3, 0.2, 0.1, 0.1, 0.5, 0.4, 0.5, 0.4, 0.3, 0.2]]
    #     res1, res2, res3 = self.sess.run([self.debug1, self.debug2, self.debug3], feed_dict={self.y: y, self.x: x})
    #     print("res1")
    #     print(res1)
    #     print("res2")
    #     print(res2)
    #     print("res3")
    #     print(res3)

    def _initialize_vars(self):
        """
        This function defines conditional probability of h|v, and reconstruction
        conditional probability of v|h and h|v.
        """
        # training momentum function
        def f(x_old, x_new):
            return self.momentum * x_old + \
                   self.learning_rate * x_new * (1 - self.momentum) / tf.to_float(tf.shape(x_new)[0])

        # probability for hidden layer
        h_prob = tf.nn.sigmoid(self.h_b + tf.matmul(self.y, self.y_w) + tf.matmul(self.x/self.x_sigma, self.x_w))

        # preparation for the probability of y|h and y|x
        # numerator of y_recon_prob
        # exp( y_b + \sum_j U_jy h_j )
        # shape: (n_y, batch_size, 1)
        y_recon_part   = tf.map_fn(
            lambda i: tf.exp(self.y_b[i] + tf.matmul(
                    sample_bernoulli(h_prob),
                    tf.transpose(tf.slice(self.y_w, [i, 0], [1, self.n_h])))),
            np.arange(self.n_y), # iterative elements (index of y nodes)
            dtype=tf.float32)    # data type for output of fn
        # denominator of y_recon_prob
        # shape: (batch_size, 1)
        y_recon_denom  = tf.reduce_sum(y_recon_part, axis=0)

        # TODO: make sure using x or recon_x?
        # precomputing b_j + \sum_i w_jk x_k
        # shape: (n_h, batch_size, n_h)
        precomp_part   = tf.map_fn(
            lambda j: self.h_b[j] + tf.matmul(self.x/self.x_sigma, self.x_w),
            np.arange(self.n_h), # iterative elements (index of h nodes)
            dtype=tf.float32)    # data type for output of fn
        # numerator of y_cond_x_prob
        # shape: (n_y, batch_size, n_h)
        y_cond_x_part  = tf.map_fn(
            lambda i: tf.exp(self.y_b[i]) * tf.cumprod(1 + tf.exp(self.y_w[i, :] + precomp_part))[-1],
            np.arange(self.n_y), # iterative elements (index of y nodes)
            dtype=tf.float32)    # data type for output of fn
        # denominator of y_recon_prob
        # shape: (batch_size, n_h)
        y_cond_x_denom = tf.reduce_sum(y_cond_x_part, axis=0)

        # reconstructed probability for both hidden & visible layers
        # shape: (n_y, batch_size, 1)
        y_recon_prob   = tf.map_fn(
            lambda x: x / y_recon_denom,
            y_recon_part,     # iterative elements (value of unnormalized y reconstruct probability)
            dtype=tf.float32) # data type for output of fn
        # shape: (batch_size, n_y)
        y_recon_prob   = tf.transpose(tf.squeeze(y_recon_prob))
        # shape: (batch_size, n_x)
        x_recon_prob   = self.x_b + tf.matmul(sample_bernoulli(h_prob), tf.transpose(self.x_w))
        # shape: (batch_size, n_h)
        h_recon_prob   = tf.nn.sigmoid(self.h_b + tf.matmul(y_recon_prob, self.y_w) + tf.matmul(x_recon_prob, self.x_w))
        # shape: (n_y, batch_size, n_h)
        y_cond_x_prob  = tf.map_fn(
            lambda x: x / y_cond_x_denom,
            y_cond_x_part,    # iterative elements (value of unnormalized y conditional probability)
            dtype=tf.float32) # data type for output of fn

        # add a gaussian random noise to x_recon_p if sample_visible is set True
        if self.sample_visible:
            x_recon_prob = sample_gaussian(x_recon_prob, self.x_sigma)

        # unsuperv loglikelihood:
        # - E_{y|x}[ E_{h|x,y} ] + E_{x,y,h}
        # superv loglikelihood:
        # - E_{h|x,y} + E_{y|x}[ E_{h|x,y} ]
        # hybrid loglikelihood:
        # E_{x,y,h} - \alpha * E_{h|x,y} + (\alpha - 1) * E_{y|x}[ E_{h|x,y} ]
        # - <grad>_{model} + \alpha * <grad>_{data} + (1 - \alpha) * p(y|x) * <grad>_{data}

        # update weights by gradient
        delta_y_w_new = f(self.delta_y_w,
            self.alpha * tf.matmul(tf.transpose(self.y), h_prob) - # positive phase of data gradient
            tf.matmul(tf.transpose(y_recon_prob), h_recon_prob) +  # negative phase of model gradient
            (1-self.alpha) *
                tf.matmul(tf.transpose(self.y), h_prob))           # weighted average of data gradient
        delta_x_w_new = f(self.delta_x_w,
            self.alpha * tf.matmul(tf.transpose(self.x/self.x_sigma), h_prob) - # positive phase of data gradient
            tf.matmul(tf.transpose(x_recon_prob), h_recon_prob) +               # negative phase of model gradient
            (1-self.alpha) *
                tf.matmul(tf.transpose(self.x/self.x_sigma), h_prob))           # weighted average of data gradient

        delta_y_b_new = f(self.delta_y_b, tf.reduce_mean(self.y - y_recon_prob, axis=0))
        delta_x_b_new = f(self.delta_x_b, tf.reduce_mean(self.x - x_recon_prob, axis=0))
        delta_h_b_new = f(self.delta_h_b, tf.reduce_mean(h_prob - h_recon_prob, axis=0))

        update_delta_y_w = self.delta_y_w.assign(delta_y_w_new)
        update_delta_x_w = self.delta_x_w.assign(delta_x_w_new)
        update_delta_y_b = self.delta_y_b.assign(delta_y_b_new)
        update_delta_x_b = self.delta_x_b.assign(delta_x_b_new)
        update_delta_h_b = self.delta_h_b.assign(delta_h_b_new)

        update_y_w = self.y_w.assign(self.y_w + delta_y_w_new)
        update_x_w = self.x_w.assign(self.x_w + delta_x_w_new)
        update_y_b = self.y_b.assign(self.y_b + delta_y_b_new)
        update_x_b = self.x_b.assign(self.x_b + delta_x_b_new)
        update_h_b = self.h_b.assign(self.h_b + delta_h_b_new)

        self.update_deltas = [update_delta_y_w, update_delta_x_w,
            update_delta_y_b, update_delta_x_b, update_delta_h_b]
        self.update_weights = [update_y_w, update_x_w,
            update_y_b, update_x_b, update_h_b]

        self.compute_hidden = tf.nn.sigmoid(tf.matmul(self.x, self.x_w) + self.h_b)
        self.compute_visible = tf.matmul(self.compute_hidden, tf.transpose(self.x_w)) + self.x_b
        self.compute_visible_from_hidden = tf.matmul(self.h, tf.transpose(self.x_w)) + self.x_b

        # self.debug1 = y_recon_prob
        # self.debug2 = tf.shape(y_recon_prob)
        # self.debug3 = y_recon_prob

    def get_err(self, batch_x):
        return self.sess.run(self.compute_err, feed_dict={self.x: batch_x})

    def transform(self, batch_x):
        return self.sess.run(self.compute_hidden, feed_dict={self.x: batch_x})

    def transform_inv(self, batch_y):
        return self.sess.run(self.compute_visible_from_hidden, feed_dict={self.y: batch_y})

    def reconstruct(self, batch_x):
        return self.sess.run(self.compute_visible, feed_dict={self.x: batch_x})

    def partial_fit(self, batch_x, batch_y):
        self.sess.run(self.update_weights + self.update_deltas, feed_dict={self.x: batch_x, self.y: batch_y})

    def fit(self, data_x, data_y,
        n_epoches=10, batch_size=10, shuffle=True):
        """
        A customized fitting method for supervised learning RBM. There are only
        several minor changes compared to 'fit' method in tfrbm in order to
        incorporate target labelings.
        """
        assert n_epoches  > 0
        assert batch_size > 0
        assert len(data_y) == len(data_x)

        # number of data records
        n_data    = data_x.shape[0]
        # number of batches
        n_batches = n_data / batch_size + (0 if n_data % batch_size == 0 else 1)

        # prepare for shuffling the dataset
        if shuffle:
            data_x_cpy = data_x.copy()
            data_y_cpy = data_y.copy()
            inds = np.arange(n_data)
        else:
            data_x_cpy = data_x
            data_y_cpy = data_y

        # logging the training errors
        # errs = []
        # iterate training epoches
        for e in range(n_epoches):
            # shuffle dataset
            if shuffle:
                np.random.shuffle(inds)
                data_x_cpy = data_x_cpy[inds]
                data_y_cpy = data_y_cpy[inds]

            # init the array of errors of each epoches
            epoch_errs = np.zeros((n_batches,))
            # epoch_accs = np.zeros((n_batches,))
            epoch_ind  = 0
            # iterate each batch of dataset
            for b in range(n_batches):
                batch_x = data_x_cpy[b*batch_size:(b+1)*batch_size]
                batch_y = data_y_cpy[b*batch_size:(b+1)*batch_size]
                self.partial_fit(batch_x, batch_y) # supervised fitting partially
                batch_err = self.get_err(batch_x)  # get errors after one batch training
                # batch_acc = self.get_superv_acc(batch_x, batch_y)
                epoch_errs[epoch_ind] = batch_err
                # epoch_accs[epoch_ind] = batch_acc
                epoch_ind += 1

            # get mean of errors in this epoch
            err_mean = epoch_errs.mean()
            # acc_mean = epoch_accs.mean()
            print("Epoch: {:d}".format(e), file=sys.stderr)
            print("Train error: {:.4f}".format(err_mean), file=sys.stderr)
            # print("Train acc: {:.4f}".format(acc_mean), file=sys.stderr)
            # errs = np.hstack([errs, epoch_errs])
        # return errs

    def get_weights(self):
        return self.sess.run(self.y_w),\
               self.sess.run(self.x_w),\
               self.sess.run(self.y_b),\
               self.sess.run(self.x_b), \
               self.sess.run(self.h_b)

    # def save_weights(self, filename, name):
    #     saver = tf.train.Saver({name + '_w':  self.w,
    #                             name + '_bv': self.bvisible_bias,
    #                             name + '_gv': self.gvisible_bias,
    #                             name + '_h':  self.hidden_bias})
    #     return saver.save(self.sess, filename)

    # def set_weights(self, w, bvisible_bias, gvisible_bias, hidden_bias):
    #     self.sess.run(self.w.assign(w))
    #     self.sess.run(self.bvisible_bias.assign(bvisible_bias))
    #     self.sess.run(self.gvisible_bias.assign(gvisible_bias))
    #     self.sess.run(self.hidden_bias.assign(hidden_bias))

    # def load_weights(self, filename, name):
    #     saver = tf.train.Saver({name + '_w':  self.w,
    #                             name + '_bv': self.bvisible_bias,
    #                             name + '_gv': self.gvisible_bias,
    #                             name + '_h':  self.hidden_bias})
    #     saver.restore(self.sess, filename)

if __name__ == "__main__":
    rbm = SemiSupervRBM(n_y=3, n_x=10, n_h=5, alpha=0.1, batch_size=2, \
                        learning_rate=0.01, momentum=0.95, err_function='mse', \
                        sample_visible=False)
    # rbm.test()