from __future__ import print_function, absolute_import, unicode_literals, division

import os
from collections import OrderedDict

from classify.concreteness import cluster_after_concreteness
from classify.main_model import video_text_concat_elmo
from classify.preprocess import get_data, load_embeddings, get_embeddings_by_type, get_matrix_word_embedding
from classify.lstm import train_elmo, train_lstm
import argparse

from classify.svm import train_svm
from classify.utils import get_all_combinations
from classify.visualization import print_scores_per_method
from classify.yolo import process_output_yolo, measure_similarity


def parse_args():
    parser = argparse.ArgumentParser()
    # noinspection PyTypeChecker
    parser.add_argument('--path-miniclips', type=str, choices=["/local/oignat/miniclips/",
                                                               "/scratch/mihalcea_fluxg/oignat/Research/Data/miniclips/miniclips/",
                                                               "/home/oignat/Research/Data/miniclips/"],
                        default="/local/oignat/miniclips/")

    parser.add_argument('--balance', type=str, choices=["upsample", "downsample", "unbalanced"], default="unbalanced")

    parser.add_argument('--do-classify', nargs='+',
                        choices=['lstm', 'elmo', 'svm', 'concreteness', 'yolo', 'multimodal'])

    parser.add_argument('--finetune', action='store_true')
    parser.add_argument('--do-extract-video-features', action='store_true')

    parser.add_argument('--do-sample', action='store_true')

    parser.add_argument('--type-feat', nargs='+', choices=['inception', 'inception + c3d', 'c3d'],
                        default=['inception + c3d'])
    parser.add_argument('--type-concr', nargs='+', choices=['noun + vb', 'noun', 'vb', 'all'],
                        default=['noun + vb'],
                        help='type of concreteness score: noun + vb = maximum score between all nouns and verbs in the action')

    parser.add_argument('--do-combine', action='store_true')
    parser.add_argument('--add-extra', nargs='*',
                        choices=["pos", "context", "concreteness", "prev-next-action", "visual-c3d-inception"],
                        default=[""])

    args = parser.parse_args()
    return args


dimension_embedding = 50
args = parse_args()
dict_results = OrderedDict()
dict_significance = OrderedDict()

if not os.path.exists('data/Model_params/bestmodel/'):
    os.makedirs('data/Model_params/bestmodel/')

if not os.path.exists('data/Model_params/tensorboard/'):
    os.makedirs('data/Model_params/tensorboard/')


def store_results(method, list_results, predicted):
    if method not in dict_results.keys():
        dict_results[method] = []
    dict_results[method].append(list(list_results))
    dict_significance[method] = predicted


def call_classify(do_classify, train_data, test_data, val_data, embeddings_index, add_extra, type_concreteness):
    global dict_results
    global dict_significance

    if "lstm" == do_classify:
        embedding_matrix_for_pretrain, max_length = get_matrix_word_embedding(embeddings_index, train_data, test_data,
                                                                              val_data)
        x_train, x_test, x_val = get_embeddings_by_type("padding", [],
                                                        embeddings_index, train_data,
                                                        test_data, val_data, type_concreteness)
        list_results, predicted = train_lstm(embedding_matrix_for_pretrain, x_train, x_test, x_val, train_data,
                                             test_data,
                                             val_data)

        method = args.balance
        method += ' lstm word embed pre-trained' + " padding"
        store_results(method, list_results, predicted)

    if "elmo" == do_classify:
        # just elmo embeddings on top of dense layer
        list_results, predicted = train_elmo(train_data, test_data, val_data)

        method = args.balance
        method += ' elmo '
        if add_extra:
            method += ' + ' + str(add_extra)
        store_results(method, list_results, predicted)

    if "svm" == do_classify:
        x_train, x_test, x_val = get_embeddings_by_type("action", add_extra,
                                                        embeddings_index, train_data,
                                                        test_data, val_data, type_concreteness)
        list_results, predicted = train_svm(args.finetune, x_train, x_test, x_val,
                                            train_data, test_data, val_data, add_extra)
        method = args.balance
        method += ' SVM '
        if args.finetune:
            method += ' finetuned + ' + method

        if add_extra:
            method += ' + ' + str(add_extra)
        store_results(method, list_results, predicted)

    if 'multimodal' == do_classify:
        x_train, x_test, x_val = get_embeddings_by_type("action", add_extra,
                                                        embeddings_index, train_data,
                                                        test_data, val_data, type_concreteness)
        list_results, predicted = video_text_concat_elmo(args.param_epochs, train_data, test_data, val_data, x_train,
                                                         x_test,
                                                         x_val, args.type_feat, add_extra,
                                                         avg_or_concatenate='concat')
        method = args.balance
        method += ' multimodal: elmo + ' + str(args.type_feat)
        if add_extra:
            method += ' + ' + str(add_extra)
        store_results(method, list_results, predicted)

    if "concreteness" == do_classify:
        # get_all_words_concreteness_scores(concreteness_words_txt = "data/Concreteness_ratings_Brysbaert_et_al_BRM.txt")\
        list_results, predicted = cluster_after_concreteness(type_concreteness, train_data, test_data, val_data)

        method = args.balance
        method += ' concreteness ' + type_concreteness + ' max score'
        store_results(method, list_results, predicted)
        # save_concreteness_dict(dict_video_actions)

    if "yolo" == do_classify:
        similarity_methods = ['wup_sim', 'cos_sim all', 'cos_sim nouns']
        objects_dict = process_output_yolo("data/Video/YOLO/miniclips_results/")

        similarity_method = similarity_methods[2]
        threshold = 0.8  # after finetuning on val_data
        list_results, predicted = measure_similarity(similarity_method, threshold, objects_dict,
                                                     embeddings_index, train_data, test_data, val_data)

        method = args.balance
        method += ' YOLO ' + similarity_method + ' ' + str(threshold)
        store_results(method, list_results, predicted)


def classify(train_data, test_data, val_data, embeddings_index):
    if args.do_classify:
        if args.do_combine:
            list_subsets = get_all_combinations(args.add_extra)
            for add_extra in list_subsets:
                call_classify(args.do_classify[0], train_data, test_data, val_data,
                              embeddings_index,
                              add_extra, args.type_concr[0])

        else:
            call_classify(args.do_classify[0], train_data, test_data, val_data,
                          embeddings_index,
                          args.add_extra, args.type_concr[0])


def process_data_channel(balance, channel_test=1, channel_val=10):
    dict_video_actions, dict_train_data, dict_test_data, dict_val_data, train_data, test_data, val_data = \
        get_data(balance, channel_test, channel_val)

    if args.do_sample:
        dict_video_actions, train_data, test_data, val_data = {k: dict_video_actions[k] for k in
                                                               dict_video_actions.keys()[:20]}, train_data[
                                                                                                0:200], test_data[
                                                                                                        0:20], val_data[
                                                                                                               0:20]
    return dict_video_actions, train_data, test_data, val_data


def main():
    args = parse_args()

    # do this just once!
    embeddings_index = load_embeddings()

    dict_video_actions, train_data, test_data, val_data = process_data_channel(args.balance)
    # measure_nb_unique_actions(dict_video_actions)

    classify(train_data, test_data, val_data, embeddings_index)
    print_scores_per_method(dict_results)

    # # Calculate Significance
    # if len(dict_significance.keys()) == 2:
    #     if args.do_cross_val:
    #         calculate_significance_between_2models(dict_mean_results_method)
    #     else:
    #         print_t_test_significance(dict_results)


if __name__ == '__main__':
    main()
