import torch
import torch.nn as nn
from torch.autograd import Variable
import onmt.modules

def _makeFeatEmbedder(opt, dicts):
    return onmt.FeaturesEmbedding(dicts['features'],
                                  opt.feat_vec_exponent,
                                  opt.feat_vec_size,
                                  opt.feat_merge)


class Encoder(nn.Container):

    def __init__(self, opt, dicts):
        self.layers = opt.layers
        self.hidden_size = opt.rnnSize
        inputSize = opt.word_vec_size
        feat_lut = None
        # Sequences with features.
        if len(dicts['features']) > 0:
            feat_lut = _makeFeatEmbedder(opt, dicts)
            inputSize = inputSize + feat_lut.outputSize

        super(Encoder, self).__init__(
            word_lut=nn.Embedding(dicts['words'].size(), opt.word_vec_size),
            rnn=nn.LSTM(inputSize, opt.rnnSize,
                        num_layers=opt.layers,
                        dropout=opt.dropout,
                        bidirectional=opt.brnn)
        )

        if opt.pre_word_vecs_enc is not None:
            pretrained = torch.load(opt.pre_word_vecs_enc)
            self.word_lut.weight.copy_(pretrained)

        self.has_features = feat_lut is not None
        if self.has_features:
            self.add_module('feat_lut', feat_lut)

    def forward(self, input):
        if self.has_features:
            word_emb = self.word_lut(input[0])
            feat_emb = self.feat_lut(input[1])
            emb = torch.cat([word_emb, feat_emb], 1)
        else:
            emb = self.word_lut(input)

        batch_size = emb.size(1)
        h_0 = Variable(emb.data.new(self.layers, batch_size, self.hidden_size),
                       requires_grad=False)
        c_0 = Variable(emb.data.new(self.layers, batch_size, self.hidden_size),
                       requires_grad=False)
        outputs, _ = self.rnn(emb, (h_0, c_0))
        return outputs


class Decoder(nn.Container):

    def __init__(self, opt, dicts):
        self.layers = opt.layers
        self.input_feed = opt.input_feed
        input_size = opt.word_vec_size
        if self.input_feed:
            input_size += opt.rnnSize

        feat_lut = None
        # Sequences with features.
        if len(dicts['features']) > 0:
            feat_lut = _makeFeatEmbedder(opt, dicts)
            input_size = input_size + feat_lut.outputSize

        super(Decoder, self).__init__(
            word_lut=nn.Embedding(dicts['words'].size(), opt.word_vec_size),
            rnn=nn.LSTMCell(input_size, opt.rnnSize),
            attn=onmt.modules.GlobalAttention(opt.rnnSize),
            dropout=nn.Dropout(opt.dropout),
            generator=onmt.modules.Generator(opt.rnnSize, dicts['words'].size())
        )

        self.hidden_size = self.rnn.weight_hh.data.size(1)

        if opt.pre_word_vecs_enc is not None:
            pretrained = torch.load(opt.pre_word_vecs_dec)
            self.word_lut.weight.copy_(pretrained)

        self.has_features = feat_lut is not None
        if self.has_features:
            self.add_module('feat_lut', feat_lut)

    def forward(self, input, context):
        if self.has_features:
            word_emb = self.word_lut(input[0])
            feat_emb = self.feat_lut(input[1])
            emb = torch.cat([word_emb, feat_emb], 1)
        else:
            emb = self.word_lut(input)

        batch_size = input.size(1)

        output = Variable(emb.data.new(batch_size, self.hidden_size).zero_(),
                          requires_grad=False)
        h_0 = Variable(emb.data.new(batch_size, self.hidden_size),
                       requires_grad=False)
        c_0 = Variable(emb.data.new(batch_size, self.hidden_size),
                       requires_grad=False)
        hidden = (h_0, c_0)

        outputs = []
        for emb_t in emb.chunk(emb.size(0)):
            emb_t = emb_t.squeeze(0)
            if self.input_feed:
                emb_t = torch.cat([emb_t, output], 1)

            # FIXME: multilayer
            hidden = self.rnn(emb_t, hidden)
            output = hidden[0]
            output = self.attn(output, context.t())
            output = self.dropout(output)
            outputs += [output]

        outputs = torch.cat(outputs)
        pred = self.generator(outputs)
        return pred


class Translator(nn.Container):

    def __init__(self, enc, dec):
        super(Translator, self).__init__(
            enc=enc,
            dec=dec
        )

    def forward(self, input):
        context = self.enc(input[0])
        out = self.dec(input[1], context)
        return out
