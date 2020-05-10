from __future__ import unicode_literals, print_function, division
from io import open
import unicodedata
import string
import re
import random
import time
import math
import torch
import torch.nn as nn
from torch import optim
import torch.nn.functional as F
import matplotlib.pyplot as plt
plt.switch_backend('agg')
import matplotlib.ticker as ticker
import numpy as np
from os import system
from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu




"""========================================================================================
The sample.py includes the following template functions:

1. Encoder, decoder
2. Training function
3. BLEU-4 score function
4. Gaussian score function

You have to modify them to complete the lab.
In addition, there are still other functions that you have to 
implement by yourself.

1. The reparameterization trick
2. Your own dataloader (design in your own way, not necessary Pytorch Dataloader)
3. Output your results (BLEU-4 score, conversion words, Gaussian score, generation words)
4. Plot loss/score
5. Load/save weights

There are some useful tips listed in the lab assignment.
You should check them before starting your lab.
========================================================================================"""

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SOS_token = 0
EOS_token = 1
#----------Hyper Parameters----------#
hidden_size = 256
#The number of vocabulary
vocab_size = 28
lantent_size = 32
teacher_forcing_ratio = 0.8
empty_input_ratio = 0.1
KLD_weight = 0.0
LR = 0.05

CHECKPOINT_PATH = 'D:/user/Desktop/DL/Lab/DL_Lab5/checkpoint'

################################
#Example inputs of compute_bleu
################################
#The target word
reference = 'accessed'
#The word generated by your model
output = 'access'

#compute BLEU-4 score
def compute_bleu(output, reference):
    cc = SmoothingFunction()
    if len(reference) == 3:
        weights = (0.33,0.33,0.33)
    else:
        weights = (0.25,0.25,0.25,0.25)
    return sentence_bleu([reference], output,weights=weights,smoothing_function=cc.method1)


"""============================================================================
example input of Gaussian_score

words = [['consult', 'consults', 'consulting', 'consulted'],
['plead', 'pleads', 'pleading', 'pleaded'],
['explain', 'explains', 'explaining', 'explained'],
['amuse', 'amuses', 'amusing', 'amused'], ....]

the order should be : simple present, third person, present progressive, past
============================================================================"""

def Gaussian_score(words):
    words_list = []
    score = 0
    # path of train.txt
    yourpath = 'D:/user/Desktop/DL/Lab/DL_Lab5/train.txt'
    with open(yourpath,'r') as fp:
        for line in fp:
            word = line.split(' ')
            word[3] = word[3].strip('\n')
            words_list.extend([word])
        for t in words:
            for i in words_list:
                if t == i:
                    score += 1
    return score/len(words)


# Turn a Unicode string to plain ASCII, thanks to
# https://stackoverflow.com/a/518232/2809427
def unicodeToAscii(s):
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )


def normalizeString(s):
    s = unicodeToAscii(s.lower().strip())
    return s


# Create a language for english
class Lang_Eng:
    def __init__(self):
        self.char2index = {}
        self.index2char = {0: "SOS", 1: "EOS"}
        
        # Initialize the language
        for i in range(26):
            char = chr(ord('a') + i)
            index = i + 2
            self.char2index[char] = index
            self.index2char[index] = char

class Train_Data:
    def __init__(self, word, tense_id):
        self.word = word
        self.tense = tense_id


# The train data should be the train word and the tense
# ex. ['abandon', tense_id]
# simple present(sp): 0, third person(tp): 1, present progressive(pg): 2, simple past(p): 3
def generate_train_data():
    train_datas = []
    with open('train.txt', 'r') as fp:
        all_lines = fp.readlines()

    for line in all_lines:
        words = line.split(' ')
        for id, word in enumerate(words):
            train_data = Train_Data(normalizeString(word.lower().strip()), id)
            train_datas.append(train_data)

    return train_datas


class Test_Data:
    def __init__(self, input_word, target_word, input_tense, target_tense):
        self.input_word = input_word
        self.target_word = target_word
        self.input_tense = input_tense
        self.target_tense = target_tense

# The list of test data tense
# simple present(sp): 0, third person(tp): 1, present progressive(pg): 2, simple past(p): 3
test_tense_list = \
[
    [0, 3], # sp -> p
    [0, 2], # sp -> pg
    [0, 1], # sp -> tp
    [0, 1], # sp -> tp
    [3, 1], # p -> tp
    [0, 2], # sp -> pg
    [3, 0], # p -> sp
    [2, 0], # pg -> sp
    [2, 3], # pg -> p
    [2, 1] # pg -> tp
]

def generate_test_data():
    test_datas = []
    with open('test.txt', 'r') as fp:
        all_lines = fp.readlines()

    for id, line in enumerate(all_lines):
        words = line.split(' ')
        test_tense = test_tense_list[id]
        input_word = normalizeString(words[0].lower().strip())
        target_word = normalizeString(words[1].lower().strip())
        test_data = Test_Data( input_word, target_word, test_tense[0], test_tense[1])
        test_datas.append(test_data)
    return test_datas


def indexs_from_word(word):
    indexs = []
    for char in word:
        indexs.append(lang.char2index[char])
    return indexs


#Encoder
class EncoderRNN(nn.Module):
    def __init__(self, input_size, hidden_size, lantent_size):
        super(EncoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.class_num = 4
        self.lantent_size = lantent_size
        # Because we concat the condition at the end of hidden
        self.c_hidden_size = self.hidden_size + self.class_num
        
        # The hidden size become the hidden size + 4
        self.embedding = nn.Embedding(input_size, self.c_hidden_size)
        self.lstm = nn.LSTM(self.c_hidden_size, self.c_hidden_size)
        self.hidden2mean = nn.Linear(self.c_hidden_size*2, lantent_size)
        self.hidden2logv = nn.Linear(self.c_hidden_size*2, lantent_size)

    def forward(self, input_tensor, hidden):
        input_length = input_tensor.size(0)
        for ei in range(input_length):
            if input_tensor[ei] == EOS_token:
                hidden = torch.cat((hidden[0], hidden[1]), dim = 2)
                mean = self.hidden2mean(hidden)
                logv = self.hidden2logv(hidden)
                z = self.reparameterize(mean, logv)
                break

            embedded = self.embedding(input_tensor[ei]).view(1, 1, -1)
            output = embedded
            output, hidden = self.lstm(output, hidden)

        return z, mean, logv
    
    def reparameterize(self, mean, logv):
        std = torch.exp(0.5 * logv)
        eps = torch.randn_like(std)
        return eps*std + mean

    def initHidden(self):
        return torch.zeros(1, 1, self.hidden_size, device=device)

#Decoder
class DecoderRNN(nn.Module):
    def __init__(self, hidden_size, output_size, lantent_size):
        super(DecoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.n_class = 4
        self.c_hidden_size = hidden_size + self.n_class
        
        # Make the lantent vector size = hidden size
        self.lantent2hidden = nn.Linear(lantent_size, self.hidden_size)
        # Embed the input to the size of hidden
        self.embedding = nn.Embedding(output_size, self.c_hidden_size)
        self.lstm = nn.LSTM(self.c_hidden_size, self.c_hidden_size)
        self.out = nn.Linear(self.c_hidden_size, output_size)
        self.softmax = nn.LogSoftmax(dim=1)

    def forward(self, input, hidden, tense):
        if input == SOS_token:
            hidden = self.lantent2hidden(hidden).view(1, 1, -1)
            # Concate the condition
            hidden = torch.cat((hidden, tense), dim = 2)
            hidden = (hidden, hidden)
        
        output = self.embedding(input).view(1, 1, -1)
        output = F.relu(output)
        output, hidden = self.lstm(output, hidden)
        output = self.softmax(self.out(output[0]))
        return output, hidden

    def initHidden(self):
        return torch.zeros(1, 1, self.hidden_size, device=device)


def create_onehot(tense):
    onehot = np.array([0, 0, 0, 0])
    onehot[tense] = 1
    onehot = torch.from_numpy(onehot)
    onehot = onehot.view(1, 1, -1).type(torch.FloatTensor)
    onehot = onehot.to(device)
    return onehot


MAX_LENGTH = 20
def train(input_tensor, target_tensor, tense, encoder, decoder, encoder_optimizer, decoder_optimizer, criterion, kld_weight_update,max_length=MAX_LENGTH):

    #---------------------add condition-----------------------#
    encoder_hidden = encoder.initHidden()
    # Create a onehot vector by tense
    onehot = create_onehot(tense)
    # Concate the onehot vector and hidden
    encoder_hidden = torch.cat((encoder_hidden, onehot), dim = 2)
    encoder_hidden = (encoder_hidden, encoder_hidden)
    
    encoder_optimizer.zero_grad()
    decoder_optimizer.zero_grad()
    
    target_length = target_tensor.size(0)
    
    # Cross entropy loss
    kl_loss = 0
    ce_loss = 0

    # Total loss
    loss = 0
    
    #----------sequence to sequence part for encoder----------#
    z, mean, logv = encoder(input_tensor, encoder_hidden)
    
    # Compute kl_loss
    kl_loss = -0.5 * torch.sum(1 + logv - mean.pow(2) - logv.exp())

    decoder_input = torch.tensor([[SOS_token]], device=device)
    
    # Sampling vector from encoder is input hidden of decoder
    decoder_hidden = z

    use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False

    #----------sequence to sequence part for decoder----------#
    if use_teacher_forcing:
        # Teacher forcing: Feed the target as the next input
        for di in range(target_length):
            decoder_output, decoder_hidden = decoder(decoder_input, decoder_hidden, onehot)
            ce_loss += criterion(decoder_output, target_tensor[di])
            decoder_input = target_tensor[di]  # Teacher forcing

    else:
        # Without teacher forcing: use its own predictions as the next input
        for di in range(target_length):
            decoder_output, decoder_hidden = decoder(decoder_input, decoder_hidden, onehot)
            topv, topi = decoder_output.topk(1)
            decoder_input = topi.squeeze().detach()  # detach from history as input

            ce_loss += criterion(decoder_output, target_tensor[di])
            if decoder_input.item() == EOS_token:
                break
   
    # Compute total loss
    loss += ce_loss + kld_weight_update*kl_loss
    loss.backward()

    encoder_optimizer.step()
    decoder_optimizer.step()

    return loss.item()/target_length, ce_loss.item(), kl_loss.item()


def asMinutes(s):
    m = math.floor(s / 60)
    s -= m * 60
    return '%dm %ds' % (m, s)


def timeSince(since, percent):
    now = time.time()
    s = now - since
    es = s / (percent)
    rs = es - s
    return '%s (- %s)' % (asMinutes(s), asMinutes(rs))


def tensorFromWord(word):
    indexes = [lang.char2index[char] for char in word]
    indexes.append(EOS_token)
    return torch.tensor(indexes, dtype=torch.long, device=device).view(-1, 1)


def trainIters(encoder, decoder, n_iters, print_every=1000, plot_every=100, save_every=5000, learning_rate=0.01):
    start = time.time()
    
    # Store total loss: CE + KL
    plot_losses = []
    # Store cross entropy loss
    plot_CE_losses = []
    # Store KL-Divergence loss
    plot_KL_losses = []
    # Store bleu scores
    plot_scores = []
    # Store KLD weights
    plot_kld_weights = []

    print_loss_total = 0  # Reset every print_every
    print_ce_loss_total = 0
    print_kl_loss_total = 0
    plot_loss_total = 0  # Reset every plot_every
    plot_ce_loss_total = 0
    plot_kl_loss_total = 0

    encoder_optimizer = optim.SGD(encoder.parameters(), lr=learning_rate)
    decoder_optimizer = optim.SGD(decoder.parameters(), lr=learning_rate)
    training_datas = [random.choice(train_datas) for i in range(n_iters)]
    criterion = nn.CrossEntropyLoss()

    kld_weight_update = KLD_weight
    count_hold = 0

    for iter in range(1, n_iters + 1):
        # Training mode
        encoder = encoder.train()
        decoder = decoder.train()

        training_data = training_datas[iter - 1]
        
        # In this task, when training, we use same word at training and testing time.
        input_tensor = tensorFromWord(training_data.word)
        target_tensor = tensorFromWord(training_data.word)

        # Because we are working on condition task, so we add tense as condition.
        tense = training_data.tense

        loss, ce_loss, kl_loss = train(input_tensor, target_tensor, tense, encoder,
                                decoder, encoder_optimizer, decoder_optimizer, criterion, kld_weight_update)
        
        print_loss_total += loss
        print_ce_loss_total += ce_loss
        print_kl_loss_total += kl_loss

        plot_loss_total += loss
        plot_ce_loss_total += ce_loss
        plot_kl_loss_total += kl_loss

        if iter % print_every == 0:
            print_loss_avg = print_loss_total / print_every
            print_ce_loss_avg = print_ce_loss_total / print_every
            print_kl_loss_avg = print_kl_loss_total / print_every
            print_loss_total = 0
            print_ce_loss_total = 0
            print_kl_loss_total = 0

            print('%s (%d %d%%) Total Loss: %.4f, Cross Entropy Loss: %.4f, KL_Loss: %.4f' % (timeSince(start, iter / n_iters),
                                         iter, iter / n_iters * 100, print_loss_avg, print_ce_loss_avg, print_kl_loss_avg))
            print("KLD", kld_weight_update)
            
            encoder = encoder.eval()
            decoder = decoder.eval()
            bleu_score = evaluate_bleu(encoder, decoder)
            print("Bleu score %4f" % bleu_score)
            plot_scores.append(bleu_score)
        
        if iter % plot_every == 0:
            plot_loss_avg = plot_loss_total / plot_every
            plot_ce_loss_avg = plot_ce_loss_total / plot_every
            plot_kl_loss_avg = plot_kl_loss_total / plot_every
            plot_loss_total = 0
            plot_ce_loss_total = 0
            plot_kl_loss_total = 0

            plot_losses.append(plot_loss_avg)
            plot_CE_losses.append(plot_ce_loss_avg)
            plot_KL_losses.append(plot_kl_loss_avg)

            plot_kld_weights.append(kld_weight_update)

        if iter % 200 == 0:
            if kld_weight_update < 0.6:
                count_hold = 0
                kld_weight_update += 0.003
            else:
                count_hold += 1
                kld_weight_update = 0.6
                if count_hold > (5000/200):
                    count_hold = 0
                    kld_weight_update = 0
        
        if iter % save_every == 0:
            torch.save(encoder.state_dict(), CHECKPOINT_PATH + '/encoder' + str(iter) + '.pth')
            torch.save(decoder.state_dict(), CHECKPOINT_PATH + '/decoder' + str(iter) + '.pth')

            # Evaluate test datas
            encoder = encoder.eval()
            decoder = decoder.eval()
            print_bleu(encoder, decoder)
    
    # Plot the imgs
    plot_imgs(plot_losses, "Total Loss", 0.2)
    plot_imgs(plot_CE_losses, "Cross Entropy Loss", 1.0)
    plot_imgs(plot_KL_losses, "KL-Divergence Loss", 5.0)
    plot_imgs(plot_scores, "Bleu scores", 0.2)
    plot_imgs(plot_kld_weights, "KLD weights", 0.1)


def plot_imgs(points, plot_type, base_num):
    plt.figure()
    fig, ax = plt.subplots()
    # this locator puts ticks at regular intervals
    loc = ticker.MultipleLocator(base=base_num)
    ax.yaxis.set_major_locator(loc)
    plt.plot(points)
    plt.savefig(plot_type + '.png')


def evaluate(encoder, decoder, test_data, max_length=MAX_LENGTH):
    with torch.no_grad():
        input_tensor = tensorFromWord(test_data.input_word)
        
        #---------------------add condition-----------------------#
        encoder_hidden = encoder.initHidden()
        # Create a onehot vector by input tense
        input_onehot = create_onehot(test_data.input_tense)
        # Concate the input onehot vector and hidden
        encoder_hidden = torch.cat((encoder_hidden, input_onehot), dim = 2)
        encoder_hidden = (encoder_hidden, encoder_hidden)
        
        #----------sequence to sequence part for encoder----------#
        z, mean, logv = encoder(input_tensor, encoder_hidden)
        
        #----------sequence to sequence part for decoder----------#
        decoder_input = torch.tensor([[SOS_token]], device=device)  # SOS
        
        # Sampling vector from encoder is input hidden of decoder 
        decoder_hidden = z
        # Create a onehot vector by target tense
        target_onehot = create_onehot(test_data.target_tense)

        decoded_words = []
        for di in range(max_length):
            decoder_output, decoder_hidden = decoder(decoder_input, decoder_hidden, target_onehot)
            topv, topi = decoder_output.data.topk(1)
            if topi.item() == EOS_token:
                decoded_words.append('<EOS>')
                break
            else:
                decoded_words.append(lang.index2char[topi.item()])

            decoder_input = topi.squeeze().detach()

        return decoded_words


def evaluate_bleu(encoder, decoder):
    total_bleu = 0.0
    for test_data in test_datas:
        output_words = evaluate(encoder, decoder, test_data)
        output_sentence = ''.join(output_words)
        bleu = compute_bleu(output_sentence[:len(output_sentence)-5], test_data.target_word)
        total_bleu += bleu
    return total_bleu/len(test_datas)


def print_bleu(encoder, decoder):
    total_bleu = 0.0
    for test_data in test_datas:
        print('input: ', test_data.input_word)
        print('target: ', test_data.target_word)
        output_words = evaluate(encoder, decoder, test_data)
        output_sentence = ''.join(output_words)
        print('pred: ', output_sentence[:len(output_sentence)-5])
        bleu = compute_bleu(output_sentence[:len(output_sentence)-5], test_data.target_word)
        print('Bleu score: ', bleu)
        total_bleu += bleu
        print('')
        bleu_score = total_bleu/len(test_datas)
    print("Avg Bleu: %4f" % bleu_score)


def decode_z_vector(decoder, eval_tense, lantent_z, max_length=MAX_LENGTH):
    #----------sequence to sequence part for decoder----------#
    # SOS
    decoder_input = torch.tensor([[SOS_token]], device=device)

    # Create a onehot vector by target tense
    target_onehot = create_onehot(eval_tense)

    decoder_hidden = lantent_z

    decoded_words = []
    for di in range(max_length):
        decoder_output, decoder_hidden = decoder(decoder_input, decoder_hidden, target_onehot)
        topv, topi = decoder_output.data.topk(1)
        if topi.item() == EOS_token:
            decoded_words.append('<EOS>')
            break
        else:
            decoded_words.append(lang.index2char[topi.item()])
        decoder_input = topi.squeeze().detach()
    return decoded_words


def evaluateGaussian(decoder):
    eval_tense_list = [0, 1, 2, 3]
    
    # Create 100 words with 4 tense by z vector
    words = []
    for count_word in range(100):
        # Sampling a z vector for each word
        lantent_z = torch.randn(lantent_size).to(device)
        
        word_tense_list = []
        for eval_tense in eval_tense_list:
            word = decode_z_vector(decoder, eval_tense, lantent_z)
            output_word = ''.join(word)
            output_word = output_word[:len(output_word)-5]
            word_tense_list.append(output_word)
        words.append(word_tense_list)
    # print(words)
    gaussian_score = Gaussian_score(words)
    print()
    print("Gaussian score: ", gaussian_score)


# Create language
lang = Lang_Eng()

# Read training data
print("Reading train data...")
train_datas = generate_train_data()

print("Reading test data...")
test_datas = generate_test_data()

# encoder1 = EncoderRNN(vocab_size, hidden_size, lantent_size).to(device)
# decoder1 = DecoderRNN(hidden_size, vocab_size, lantent_size).to(device)
# trainIters(encoder1, decoder1, 200000, print_every=1000, save_every=5000)

# For evaluate bleu 
encoder_eval1 = EncoderRNN(vocab_size, hidden_size, lantent_size).to(device)
encoder_eval1.load_state_dict(torch.load(CHECKPOINT_PATH + '/encoder185000.pth'))
encoder_eval1 = encoder_eval1.eval()

decoder_eval1 = DecoderRNN(hidden_size, vocab_size, lantent_size).to(device)
decoder_eval1.load_state_dict(torch.load(CHECKPOINT_PATH + '/decoder185000.pth'))
decoder_eval1 = decoder_eval1.eval()
print_bleu(encoder_eval1, decoder_eval1)

# For evaluate gaussian
decoder_eval2 = DecoderRNN(hidden_size, vocab_size, lantent_size).to(device)
decoder_eval2.load_state_dict(torch.load(CHECKPOINT_PATH + '/decoder135000.pth'))
decoder_eval2 = decoder_eval2.eval()
evaluateGaussian(decoder_eval2)
