# -*- coding: utf-8 -*-
#import sys
#reload(sys)
#sys.setdefaultencoding('utf-8') #gb2312
import codecs
import random
import numpy as np
from tflearn.data_utils import pad_sequences
from collections import Counter
import os
import pickle
import json
import jieba

PAD_ID = 0
UNK_ID=1
_PAD="_PAD"
_UNK="UNK"

imprisonment_mean=26.2
imprisonment_std=33.5
from predictor.data_util_test import  pad_truncate_list
def load_data_multilabel(traning_data_path,valid_data_path,test_data_path,vocab_word2index, accusation_label2index,article_label2index,
                         deathpenalty_label2index,lifeimprisonment_label2index,sentence_len,name_scope='cnn',test_mode=False):
    """
    convert data as indexes using word2index dicts.
    :param traning_data_path:
    :param vocab_word2index:
    :param vocab_label2index:
    :return:
    """
    # 1. use cache file if exist
    cache_data_dir = 'cache' + "_" + name_scope;cache_file =cache_data_dir+"/"+'train_valid_test.pik'
    print("cache_path:",cache_file,"train_valid_test_file_exists:",os.path.exists(cache_file))
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as data_f:
            print("going to load cache file from file system and return")
            return pickle.load(data_f)
    # 2. read source file
    train_file_object = codecs.open(traning_data_path, mode='r', encoding='utf-8')
    valid_file_object = codecs.open(valid_data_path, mode='r', encoding='utf-8')
    test_data_obejct = codecs.open(test_data_path, mode='r', encoding='utf-8')
    train_lines = train_file_object.readlines()
    valid_lines=valid_file_object.readlines()
    test_lines=test_data_obejct.readlines()

    train_lines.extend(test_lines)

    random.shuffle(train_lines)
    random.shuffle(valid_lines)
    random.shuffle(test_lines)

    if test_mode:
        train_lines=train_lines[0:1000]
    # 3. transform to train/valid data to standardized format
    train=transform_data_to_index(train_lines, vocab_word2index, accusation_label2index, article_label2index,deathpenalty_label2index, lifeimprisonment_label2index, sentence_len,'train',name_scope)
    valid=transform_data_to_index(valid_lines, vocab_word2index, accusation_label2index, article_label2index,deathpenalty_label2index, lifeimprisonment_label2index, sentence_len,'valid',name_scope)
    test=transform_data_to_index(test_lines, vocab_word2index, accusation_label2index, article_label2index,deathpenalty_label2index, lifeimprisonment_label2index, sentence_len,'test',name_scope)

    # 4. save to file system if vocabulary of words not exists
    if not os.path.exists(cache_file):
        with open(cache_file, 'ab') as data_f:
            print("going to dump train/valid/test data to file sytem.")
            pickle.dump((train,valid,test),data_f, protocol=4)
    return train,valid,test

splitter=':'
num_mini_examples=1900
def transform_data_to_index(lines,vocab_word2index,accusation_label2index,article_label2index,deathpenalty_label2index,lifeimprisonment_label2index,
                            sentence_len,data_type,name_scope,reverse_flag=False):
    """
    transform data to index using vocab and label dict.
    :param lines:
    :param vocab_word2index:
    :param accusation_label2index:
    :param article_label2index:
    :param deathpenalty_label2index:
    :param lifeimprisonment_label2index:
    :param sentence_len: max sentence length
    :return:
    """
    X = []
    Y_accusation = []  # discrete
    Y_article = []  # discrete
    Y_deathpenalty = []  # discrete
    Y_lifeimprisonment = []  # discrete
    Y_imprisonment = []  # continuous
    weights_accusation=[]
    weights_article=[]
    accusation_label_size=len(accusation_label2index)
    article_lable_size=len(article_label2index)

    # load frequency of accu and relevant articles, so that we can copy those data with label are few. ADD 2018-05-29
    accusation_freq_dict, article_freq_dict = load_accusation_articles_freq_dict(accusation_label2index,article_label2index, name_scope)


    for i, line in enumerate(lines):
        if i%10000==0:print("i:", i)
        json_string = json.loads(line.strip())

        # 1. transform input x.discrete
        facts = json_string['fact']
        input_list = token_string_as_list(facts)  # tokenize
        x = [vocab_word2index.get(x, UNK_ID) for x in input_list]  # transform input to index
        x=pad_truncate_list(x, sentence_len) #ADD 2018.05.24

        # 2. transform accusation.discrete
        accusation_list = json_string['meta']['accusation']
        accusation_list = [accusation_label2index[label] for label in accusation_list]
        y_accusation = transform_multilabel_as_multihot(accusation_list, accusation_label_size)

        # 3.transform relevant article.discrete
        article_list = json_string['meta']['relevant_articles']
        article_list = [article_label2index[int(label)] for label in article_list] #label-->int(label) #2018-06-13
        y_article = transform_multilabel_as_multihot(article_list, article_lable_size)

        # 4.transform death penalty.discrete
        death_penalty = json_string['meta']['term_of_imprisonment']['death_penalty']  # death_penalty
        death_penalty = deathpenalty_label2index[death_penalty]
        y_deathpenalty = transform_multilabel_as_multihot(death_penalty, 2)
        Y_deathpenalty.append(y_deathpenalty)

        # 5.transform life imprisonment.discrete
        life_imprisonment = json_string['meta']['term_of_imprisonment']['life_imprisonment']
        life_imprisonment = lifeimprisonment_label2index[life_imprisonment]
        y_lifeimprisonment = transform_multilabel_as_multihot(life_imprisonment, 2)

        # 6.transform imprisonment.continuous
        imprisonment = json_string['meta']['term_of_imprisonment']['imprisonment']  # continuous value like:10

        # OVER-SAMPLING:if it is training data, copy labels that are few based on their frequencies.
        num_copy = 1
        weight_accusation=1.0
        weight_artilce=1.0
        if data_type == 'train': #set specially weight and copy some examples when it is training data.
            freq_accusation = accusation_freq_dict[accusation_list[0]]
            freq_article = article_freq_dict[article_list[0]]
            if freq_accusation <= num_mini_examples or freq_article <= num_mini_examples:
                freq=(freq_accusation+freq_article)/2
                num_copy=max(1,num_mini_examples/freq)
                if i%1000==0: print("####################freq_accusation:",freq_accusation,"freq_article:",freq_article,";num_copy:",num_copy)
            weight_accusation, weight_artilce=get_weight_freq_article(freq_accusation, freq_article)

        for k in range(int(num_copy)):
            X.append(x)
            Y_accusation.append(y_accusation)
            Y_article.append(y_article)
            Y_deathpenalty.append(y_deathpenalty)
            Y_lifeimprisonment.append(y_lifeimprisonment)
            Y_imprisonment.append(float(imprisonment))
            weights_accusation.append(weight_accusation)
            weights_article.append(weight_artilce)

    #shuffle
    number_examples=len(X)
    X_=[]
    Y_accusation_=[]
    Y_article_=[]
    Y_deathpenalty_=[]
    Y_lifeimprisonment_=[]
    Y_imprisonment_=[]
    weights_accusation_=[]
    weights_article_=[]
    permutation = np.random.permutation(number_examples)
    for index in permutation:
        X_.append(X[index])
        Y_accusation_.append(Y_accusation[index])
        Y_article_.append(Y_article[index])
        Y_deathpenalty_.append(Y_deathpenalty[index])
        Y_lifeimprisonment_.append(Y_lifeimprisonment[index])
        Y_imprisonment_.append(Y_imprisonment[index])
        weights_accusation_.append(weights_accusation[index])
        weights_article_.append(weights_article[index])

    X_=np.array(X_)

    data = (X_, Y_accusation_, Y_article_, Y_deathpenalty_, Y_lifeimprisonment_, Y_imprisonment_,weights_accusation_,weights_article_)

    return data

def transform_multilabel_as_multihot(label_list,label_size):
    """
    convert to multi-hot style
    :param label_list: e.g.[0,1,4], here 4 means in the 4th position it is true value(as indicate by'1')
    :param label_size: e.g.199
    :return:e.g.[1,1,0,1,0,0,........]
    """
    result=np.zeros(label_size)
    #set those location as 1, all else place as 0.
    result[label_list] = 1
    return result

def transform_mulitihot_as_dense_list(multihot_list):
    length=len(multihot_list)
    result_list=[i for i in range(length) if multihot_list[i] > 0]
    return result_list


#use pretrained word embedding to get word vocabulary and labels, and its relationship with index
def create_or_load_vocabulary(data_path,predict_path,training_data_path,vocab_size,name_scope='cnn',test_mode=False):
    """
    create vocabulary
    :param training_data_path:
    :param vocab_size:
    :param name_scope:
    :return:
    """

    cache_vocabulary_label_pik='cache'+"_"+name_scope # path to save cache
    if not os.path.isdir(cache_vocabulary_label_pik): # create folder if not exists.
        os.makedirs(cache_vocabulary_label_pik)

    #0.if cache exists. load it; otherwise create it.
    cache_path =cache_vocabulary_label_pik+"/"+'vocab_label.pik'
    print("cache_path:",cache_path,"file_exists:",os.path.exists(cache_path))
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as data_f:
            print("going to load cache file.vocab of words and labels")
            return pickle.load(data_f)
    else:
        vocab_word2index={}
        vocab_word2index[_PAD]=PAD_ID
        vocab_word2index[_UNK]=UNK_ID

        accusation_label2index={}
        articles_label2index={}

        #1.load raw data
        file_object = codecs.open(training_data_path, mode='r', encoding='utf-8')
        lines=file_object.readlines()
        random.shuffle(lines)
        if test_mode:
           lines=lines[0:10000]
        #2.loop each line,put to counter
        c_inputs=Counter()
        c_accusation_labels=Counter()
        c_article_labels=Counter()
        for i,line in enumerate(lines):
            if i%10000==0:
                print(i)
            json_string = json.loads(line.strip())
            facts = json_string['fact']
            input_list = token_string_as_list(facts)
            c_inputs.update(input_list)

            accusation_list = json_string['meta']['accusation']
            c_accusation_labels.update(accusation_list)

            article_list = json_string['meta']['relevant_articles']
            c_article_labels.update(article_list)

        #3.get most frequency words
        vocab_list=c_inputs.most_common(vocab_size)
        word_vocab_file=predict_path+"/"+'word_freq.txt'
        if os.path.exists(word_vocab_file):
            print("word vocab file exists.going to delete it.")
            os.remove(word_vocab_file)
        word_freq_file=codecs.open(word_vocab_file,mode='a',encoding='utf-8')
        #put those words to dict
        for i,tuplee in enumerate(vocab_list):
            word,freq=tuplee
            word_freq_file.write(word+":"+str(freq)+"\n")
            vocab_word2index[word]=i+2

        #4.1 accusation and its frequency.
        accusation_freq_file=codecs.open(cache_vocabulary_label_pik+"/"+'accusation_freq.txt',mode='a',encoding='utf-8')
        accusation_label_list=c_accusation_labels.most_common()
        for i,tuplee in enumerate(accusation_label_list):
            label,freq=tuplee
            accusation_freq_file.write(label+":"+str(freq)+"\n")

        #4.2 accusation dict
        accusation_voc_file=data_path+"/accu.txt"
        accusation_voc_object=codecs.open(accusation_voc_file,mode='r',encoding='utf-8')
        accusation_voc_lines=accusation_voc_object.readlines()
        for i,accusation_name in enumerate(accusation_voc_lines):
            accusation_name=accusation_name.strip()
            accusation_label2index[accusation_name]=i

        #5.1 relevant article(law) and its frequency
        article_freq_file=codecs.open(cache_vocabulary_label_pik+"/"+'article_freq.txt',mode='a',encoding='utf-8')
        article_label_list=c_article_labels.most_common()
        for j,tuplee in enumerate(article_label_list):
            label,freq=tuplee
            article_freq_file.write(str(label)+":"+str(freq)+"\n")

        #5.2 relevant article dict
        article_voc_file=data_path+"/law.txt"
        article_voc_object=codecs.open(article_voc_file,mode='r',encoding='utf-8')
        article_voc_lines=article_voc_object.readlines()
        for i,law_id in enumerate(article_voc_lines):
            law_id=int(law_id.strip())
            articles_label2index[law_id]=i

        #6.save to file system if vocabulary of words not exists.
        if not os.path.exists(cache_path):
            with open(cache_path, 'ab') as data_f:
                print("going to save cache file of vocab of words and labels")
                pickle.dump((vocab_word2index, accusation_label2index,articles_label2index), data_f)

    #7.close resources
    word_freq_file.close()
    accusation_freq_file.close()
    article_freq_file.close()
    print("create_vocabulary.ended")
    return vocab_word2index, accusation_label2index,articles_label2index

def token_string_as_list(string,tokenize_style='word'):
    #string=string.decode("utf-8")
    string=replace_money_value(string)  #TODO add normalize number ADD 2018.06.11
    length=len(string)
    if tokenize_style=='char':
        listt=[string[i] for i in range(length)]
    elif tokenize_style=='word':
        listt=jieba.lcut(string)
    listt=[x for x in listt if x.strip()]
    return listt

def get_part_validation_data(valid,num_valid=6000):
    valid_X, valid_Y_accusation, valid_Y_article, valid_Y_deathpenalty, valid_Y_lifeimprisonment, valid_Y_imprisonment,weight_accusations,weight_artilces=valid
    number_examples=len(valid_X)
    permutation = np.random.permutation(number_examples)[0:num_valid]
    valid_X2, valid_Y_accusation2, valid_Y_article2, valid_Y_deathpenalty2, valid_Y_lifeimprisonment2, valid_Y_imprisonment2,weight_accusations2,weight_artilces=[],[],[],[],[],[],[],[]
    for index in permutation :
        valid_X2.append(valid_X[index])
        valid_Y_accusation2.append(valid_Y_accusation[index])
        valid_Y_article2.append(valid_Y_article[index])
        valid_Y_deathpenalty2.append(valid_Y_deathpenalty[index])
        valid_Y_lifeimprisonment2.append(valid_Y_lifeimprisonment[index])
        valid_Y_imprisonment2.append(valid_Y_imprisonment[index])
    return valid_X2,valid_Y_accusation2,valid_Y_article2,valid_Y_deathpenalty2,valid_Y_lifeimprisonment2,valid_Y_imprisonment2,weight_accusations2,weight_artilces


def load_accusation_articles_freq_dict(accusation_label2index,article_label2index,name_scope):
    cache_vocabulary_label_pik='cache'+"_"+name_scope # path to save cache
    #load dict of accusations
    accusation_freq_file = codecs.open(cache_vocabulary_label_pik + "/" + 'accusation_freq.txt', mode='r',encoding='utf-8')
    accusation_freq_lines=accusation_freq_file.readlines()
    accusation_freq_dict={}
    for i,line in enumerate(accusation_freq_lines):
        acc_label,freq=line.strip().split(splitter) #编造、故意传播虚假恐怖信息:122
        accusation_freq_dict[accusation_label2index[acc_label]]=int(freq)

    #load dict of articles
    article_freq_file = codecs.open(cache_vocabulary_label_pik + "/" + 'article_freq.txt', mode='r', encoding='utf-8')
    article_freq_lines=article_freq_file.readlines()
    article_freq_dict={}
    for i,line in enumerate(article_freq_lines):
        article_label,freq=line.strip().split(splitter) #397:3762
        article_freq_dict[article_label2index[int(article_label)]]=int(freq)
    return accusation_freq_dict,article_freq_dict


def get_weight_freq_article(freq_accusation,freq_article):
    if freq_accusation <= 100:
        weight_accusation = 3.0
    elif freq_accusation <= 200:
        weight_accusation = 2.0
    elif freq_accusation <= 500:
        weight_accusation = 1.5
    else:
        weight_accusation=1.0

    if freq_article <= 100:
        weight_artilce = 3.0
    elif freq_article <= 200:
        weight_artilce = 2.0
    elif freq_article <= 500:
        weight_artilce = 1.5
    else:
        weight_artilce=1.0
    return weight_accusation,weight_artilce


import re
def replace_money_value(string):
    #print("string:")
    #print(string)
    moeny_list = [1,2,5,7,10, 20, 30,50, 100, 200, 500, 800,1000, 2000, 5000,7000, 10000, 20000, 50000, 80000,100000,200000, 500000, 1000000,3000000,5000000,1000000000]
    double_patten = r'\d+\.\d+'
    int_patten = r'[\u4e00-\u9fa5,，.。；;]\d+[元块万千百十余，,。.;；]'
    doubles=re.findall(double_patten,string)
    ints=re.findall(int_patten,string)
    ints=[a[1:-1] for a in ints]
    #print(doubles+ints)
    sub_value=0
    for value in (doubles+ints):
        for money in moeny_list:
            if money >= float(value):
                sub_value=money
                break
        string=re.sub(str(value),str(sub_value),string)
    return string
#replace_money_value(x)

x="经审理查明，2012年上半年，被告人徐某使用蒋某提供的某某新农合本及身份证等证件，编造王某某甲亢性心脏病、脑溢血在中国人民解放军309医院的整套病历及住院费用证明，" \
  "并让桐柏县大河镇卫生院负责新农合报销的工作人员李某帮其办理新农合报销手续。从而徐某报销出新农合资金52459元。随后徐某分给蒋某某现金5000元。新农合报销资料显示王某某于" \
  "2012年6月2日至2012年7月16日在中国人民解放军第309医院以甲亢性心脏病、脑溢血住院，住院费用为95726.04元，新农合报销52459元。另查明，" \
  "被告人徐某因犯××于2015年4月9日被桐柏县人民法院判处××，并处罚金人民币××元，追缴违法所得3758.7元。刑期自2014年10月18日起至2020年10月17日止。" \
  "在河南省南阳市监狱服刑期间，发现徐某有上述漏罪。上述事实，被告人徐某在开庭审理过程中亦无异议，且有同案犯蒋某某的供述与辩解" \
  "，桐柏县新农合关于王某某的新农合报销病历及材料及中国解放军第309医院出具的证明等书证，到案证明，刑事判决书，准予解回罪犯的函，" \
  "被告人的常住人口基本信息等证据证实，足以认定。"
#x='XXXX同时从蒋2015年12月11日19时30分许某的支9号楼付宝账户中擅自转账61300余元，34534元，3599.34元，11400.123元,得到93443.454万元大幅度发，阿道夫12200元啊，得到3314342万元哦'
#result=replace_money_value(x)
#result2=jieba.lcut(result)
#for ss in result2:
#    print(ss)

#x='2018年9月7日到10号楼帮我拿1部价值5888元的手机，放到2单元，可以吗？'
#x="唐河县人民检察院指控：（一）××。2015年1月31日，被告人罗某在唐河县农33020元业银行营业厅帮不会取款操作的鹿某某取款，罗某趁机将鹿某某银行卡上的2900元存款转入自己账户后逃离。为指控上述犯罪事实，公诉机关当庭宣读和出示了被告人的供述、接处警登记表、银行卡交易笔录、被害人的陈述、现场勘查记录等相关证据。（二）××。2015年6月17日，被告人罗某尾随出售香囊的贾某某伺机作案，当晚10时许，贾某某行至唐河县泗洲宾馆后面的道内时，罗某将贾某某身上所挎提包抢走，致贾某某倒地，嘴部、腿部受伤。为指控上述犯罪事实，公诉机关当庭宣读和出示了被告人的供述、证人证言、被害人陈述、接处警登记表、现场勘查笔录等相关证据。综合上述指控，公诉机关认为，被告人罗某的行为已构成××、××，一人犯数罪，提请本院依据《中华人民共和国刑法》××、××、××之规定处罚。"
#result=replace_money_value(x)
#print("result2:",result)

#x='害人陈某1各项经济损失共计人民币35000元，并取得谅解'
#result=normalize_money(x)
#x='2某赔偿周某培各项损失30000元，取'
#result=normalize_money(x)
#x=' 同时从蒋某的支付宝账户中擅自转账1300余元。公'
#result=normalize_money(x)
#x=' 同时从蒋某的支付宝账户中擅自转账1300余元。公1400.123元'
#result=normalize_money(x)
#x='经鉴定，涉案轿车价值人民币11000元。'
#result=normalize_money(x)
#x="杭州市西湖区人民检察院指控，被告人黄某在大额债务无法归还、公司未正常经营的情况下，于2014年6月3日向被害人张某租赁宝马320i轿车一辆（价值人民币126000元）。后伪造张某的身份证、驾驶证，于同年6月6日，将车辆抵押给杭州德涵投资有限公司的吕营、王某，实际得款人民币100300元。被告人黄某将其中80000元用于归还债务，余款用于日常花销。被告人黄某的行为已构成××。对此指控，公诉机关当庭宣读和出示了证人证言、书证、鉴定意见等证据。"
#result=normalize_money(x)
#x='骗取他人财物共计11.98万元啊'
#result=normalize_money(x)
#x=''
#result=normalize_money(x)
#x=''
#training_data_path='../data/sample_multiple_label3.txt'
#vocab_size=100
#create_voabulary(training_data_path,vocab_size)
