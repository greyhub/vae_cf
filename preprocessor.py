import os
import shutil
import sys

import numpy as np
from scipy import sparse

import pandas as pd

import bottleneck as bn

class Preprocessor():
    def __init__(self, data_dir, rating_threshold):
        self.rating_threshold = rating_threshold
        self.data_dir = data_dir

    def get_count(self, tp, id):
        playcount_groupbyid = tp[[id]].groupby(id, as_index=False)
        count = playcount_groupbyid.size()
        return count

    def filter_triplets(self, tp, min_uc=5, min_sc=0):
        # Only keep the triplets for items which were clicked on by at least min_sc users. 
        if min_sc > 0:
            itemcount = self.get_count(tp, 'movieId')
            tp = tp[tp['movieId'].isin(itemcount.index[itemcount >= min_sc])]
        
        # Only keep the triplets for users who clicked on at least min_uc items
        # After doing this, some of the items will have less than min_uc users, but should only be a small proportion
        if min_uc > 0:
            usercount = self.get_count(tp, 'userId')
            tp = tp[tp['userId'].isin(usercount.index[usercount >= min_uc])]
        
        # Update both usercount and itemcount after filtering
        usercount, itemcount = self.get_count(tp, 'userId'), self.get_count(tp, 'movieId') 
        return tp, usercount, itemcount

    def split_train_test_proportion(self, data, test_prop=0.2):
        data_grouped_by_user = data.groupby('userId')
        tr_list, te_list = list(), list()

        np.random.seed(98765)

        for i, (_, group) in enumerate(data_grouped_by_user):
            n_items_u = len(group)

            if n_items_u >= 5:
                idx = np.zeros(n_items_u, dtype='bool')
                idx[np.random.choice(n_items_u, size=int(test_prop * n_items_u), replace=False).astype('int64')] = True

                tr_list.append(group[np.logical_not(idx)])
                te_list.append(group[idx])
            else:
                tr_list.append(group)

            if i % 1000 == 0:
                print("%d users sampled" % i)
                sys.stdout.flush()

        data_tr = pd.concat(tr_list)
        data_te = pd.concat(te_list)
        
        return data_tr, data_te
    

    def numerize(self, tp, profile2id, show2id):
        uid = map(lambda x: profile2id[x], tp['userId'])
        sid = map(lambda x: show2id[x], tp['movieId'])
        return pd.DataFrame(data={'uid': list(uid), 'sid': list(sid)}, columns=['uid', 'sid'])
    
    def process(self):
        # binarize the data (only keep ratings >= 3.5)
        raw_data = pd.read_csv(os.path.join(self.data_dir, 'ratings.csv'), header=0)
        raw_data = raw_data[raw_data['rating'] > 3.5]

        raw_data, user_activity, item_popularity = self.filter_triplets(raw_data)

        sparsity = 1. * raw_data.shape[0] / (user_activity.shape[0] * item_popularity.shape[0])

        print("After filtering, there are %d watching events from %d users and %d movies (sparsity: %.3f%%)" % 
              (raw_data.shape[0], user_activity.shape[0], item_popularity.shape[0], sparsity * 100))

        unique_uid = user_activity.index

        np.random.seed(98765)
        idx_perm = np.random.permutation(unique_uid.size)
        unique_uid = unique_uid[idx_perm]

        # create train/validation/test users
        n_users = unique_uid.size
        n_heldout_users = 10000

        tr_users = unique_uid[:(n_users - n_heldout_users * 2)]
        vd_users = unique_uid[(n_users - n_heldout_users * 2): (n_users - n_heldout_users)]
        te_users = unique_uid[(n_users - n_heldout_users):]

        train_plays = raw_data.loc[raw_data['userId'].isin(tr_users)]

        unique_sid = pd.unique(train_plays['movieId'])

        show2id = dict((sid, i) for (i, sid) in enumerate(unique_sid))
        profile2id = dict((pid, i) for (i, pid) in enumerate(unique_uid))

        pro_dir = os.path.join(self.data_dir, 'processed')

        if not os.path.exists(pro_dir):
            os.makedirs(pro_dir)

        with open(os.path.join(pro_dir, 'unique_sid.txt'), 'w') as f:
            for sid in unique_sid:
                f.write('%s\n' % sid)
        
        vad_plays = raw_data.loc[raw_data['userId'].isin(vd_users)]
        vad_plays = vad_plays.loc[vad_plays['movieId'].isin(unique_sid)]

        vad_plays_tr, vad_plays_te = self.split_train_test_proportion(vad_plays)

        test_plays = raw_data.loc[raw_data['userId'].isin(te_users)]
        test_plays = test_plays.loc[test_plays['movieId'].isin(unique_sid)]

        test_plays_tr, test_plays_te = self.split_train_test_proportion(test_plays)

        train_data = self.numerize(train_plays, profile2id, show2id)
        train_data.to_csv(os.path.join(pro_dir, 'train.csv'), index=False)

        vad_data_tr = self.numerize(vad_plays_tr, profile2id, show2id)
        vad_data_tr.to_csv(os.path.join(pro_dir, 'validation_tr.csv'), index=False)

        vad_data_te = self.numerize(vad_plays_te, profile2id, show2id)
        vad_data_te.to_csv(os.path.join(pro_dir, 'validation_te.csv'), index=False)

        test_data_tr = self.numerize(test_plays_tr, profile2id, show2id)
        test_data_tr.to_csv(os.path.join(pro_dir, 'test_tr.csv'), index=False)

        test_data_te = self.numerize(test_plays_te, profile2id, show2id)
        test_data_te.to_csv(os.path.join(pro_dir, 'test_te.csv'), index=False)

