## docs/markdown (LLMLingua README) @ rate 0.5

### original (first 1200 chars)

```
<div style="display: flex; align-items: center;">
    <div style="width: 100px; margin-right: 10px; height:auto;" align="left">
        <img src="images/LLMLingua_logo.png" alt="LLMLingua" width="100" align="left">
    </div>
    <div style="flex-grow: 1;" align="center">
        <h2 align="center">LLMLingua Series | Effectively Deliver Information to LLMs via Prompt Compression</h2>
    </div>
</div>

<p align="center">
    | <a href="https://llmlingua.com/"><b>Project Page</b></a> |
    <a href="https://aclanthology.org/2023.emnlp-main.825/"><b>LLMLingua</b></a> |
    <a href="https://aclanthology.org/2024.acl-long.91/"><b>LongLLMLingua</b></a> |
    <a href="https://aclanthology.org/2024.findings-acl.57/"><b>LLMLingua-2</b></a> |
    <a href="https://huggingface.co/spaces/microsoft/LLMLingua"><b>LLMLingua Demo</b></a> |
    <a href="https://huggingface.co/spaces/microsoft/LLMLingua-2"><b>LLMLingua-2 Demo</b></a> |
</p>

https://github.com/microsoft/LLMLingua/assets/30883354/eb0ea70d-6d4c-4aa7-8977-61f94bb87438

## News
- 🍩 [24/12/13] We are excited to announce the release of our KV cache-centric analysis work, [SCBench](https://aka.ms/SCBench), which evaluates long-context metho
```

### compressed (first 1200 chars)

```
<div style="display:;-items: center;">
: 100px; margin-right: 10px; height:auto; align="left">
/LLMLingua_logo. png alt="LLMLingua align="left">

-grow: 1;
 align="center">LLMLingua Series Deliver Information to LLMs via Prompt



 align="center">
 href="https://llmlingua.
 href="https://aclanthology. org/2023. emnlp-main. 825/
.. acl-long. 91
.. findings-acl. 57
./spaces/microsoft/LLMLingua>LLMLingua
./LLMLingua-2


 https://github./microsoft/LLMLingua/assets/30883354/eb0ea70d-6d4c-4aa7-8977-61f94bb87438


 [24/12/13 announce release KV cache-centric analysis work, [SCBench., evaluates long-context methods KV cache perspective.
[24/09/16] announce release KV cache offloading work, [RetrievalAttention]., accelerates long-context LLM inference vector retrieval.
 [24/07/03] announce release [MInference]. speed up Long-context LLMs inference, reduces latency pre A100 maintaining accuracy **1M tokens! information, check [paper]./abs/2407., visit [project page]./MInference.
 LLMLingua integrated [Prompt flow]../llmlingua-prompt-compression-tool., streamlined tool framework LLM-based AI applications.
 announce release **LLMLingua-2**, 3x-6x speed improvement LLMLingua! information, check
```

## prose (Wikipedia: Transformer_(deep_learning_architecture)) @ rate 0.5

### original (first 1200 chars)

```
In deep learning, the transformer is a family of artificial neural network architectures based on the multi-head attention mechanism, in which input data such as text, images, or audio, is  converted to a sequence of numerical representations called tokens, and each token is converted into a vector via lookup from a word embedding table. At each layer, each token is then contextualized within the scope of the context window with other (unmasked) tokens via a parallel multi-head attention mechanism, allowing the signal for key tokens to be amplified and less important tokens to be diminished. Because self-attention alone is permutation-invariant, transformers inject positional information, typically through positional encodings or learned positional embeddings, so token order can affect the output.
Transformers have the advantage of having no recurrent units, therefore requiring less training time than earlier recurrent neural architectures (RNNs) such as long short-term memory (LSTM). Later variations have been widely adopted for training large language models (LLMs) on large (language) datasets. Modern transformer designs are commonly grouped into encoder-only, decoder-only, and e
```

### compressed (first 1200 chars)

```
deep learning, transformer artificial neural network multi-head attention mechanism, input data text, images, audio, converted to numerical representations tokens, each converted into vector word embedding table., token contextualized context with other tokens-head attention mechanism, key tokens less important tokens diminished. self-attention permutation-invariant, transformers inject positional information, through encodings, token order output.
 Transformers no recurrent units, less training time than earlier architectures. Later variations adopted for training large language models. Modern transformer designs grouped into encoder-only, decoder-only, variants, representation learning, autoregressive generation, sequence-to-sequence tasks.

 original transformer architecture proposed 2017 paper "Attention Is All You Need" Google. predecessors for machine translation, applications. used in large-scale natural language processing, computer vision, reinforcement learning, audio, multimodal learning, robotics, playing chess. led to development pre-trained systems, generative pre-trained transformers BERT (bidirectional encoder representations.






, sequence modelling recurrent ne
```

## logs (synthetic server log) @ rate 0.5

### original (first 1200 chars)

```
2026-09-06T10:00:00Z systemd[5069]: started session 32 of user deploy
2026-09-06T10:00:01Z etcd[2389]: health check passed for backend-33 in 224ms
2026-09-06T10:00:02Z etcd[1718]: request GET /api/v1/pods latency=546ms status=200
2026-09-06T10:00:03Z etcd[3450]: request GET /api/v1/pods latency=104ms status=200
2026-09-06T10:00:04Z nginx[1628]: health check passed for backend-4 in 267ms
2026-09-06T10:00:05Z sshd[5428]: started session 22 of user deploy
2026-09-06T10:00:06Z systemd[8996]: request GET /api/v1/pods latency=228ms status=200
2026-09-06T10:00:07Z nginx[5038]: health check passed for backend-33 in 897ms
2026-09-06T10:00:08Z systemd[9982]: reconciling deployment default/web-35: 3 replicas ready
2026-09-06T10:00:09Z api-server[4066]: reconciling deployment default/web-25: 3 replicas ready
2026-09-06T10:00:10Z sshd[4360]: reconciling deployment default/web-3: 3 replicas ready
2026-09-06T10:00:11Z nginx[1414]: health check passed for backend-9 in 776ms
2026-09-06T10:00:12Z systemd[6971]: started session 14 of user deploy
2026-09-06T10:00:13Z etcd[1989]: reconciling deployment default/web-23: 3 replicas ready
2026-09-06T10:00:14Z nginx[3712]: health check passed for backend-2 
```

### compressed (first 1200 chars)

```
2026-09-06T10:00:00Z systemd: started session 32 deploy
: health check passed backend-33 224ms
: request /api/v1/pods latency=546ms status=200
: /api/v1/pods latency=104ms status=200
 nginx[1628: health check passed backend-4 267ms
: started session 22 deploy
[8996: request GET /api/v1/pods latency=228ms status=200
 nginx: health check passed backend-33 897ms
[9982]: reconciling deployment/web-35: 3 replicas ready
 api-server[4066: reconciling deployment: 3 replicas ready
[4360: reconciling deployment: 3 replicas ready
: health check passed backend-9
[6971]: started session 14 user deploy
[1989: reconciling deployment/web-23: 3 replicas ready
 nginx[3712]: health check passed backend-2 249ms
[2497: TLS handshake error...:
sshd:: disk usage /var/lib 98% 85%
 scheduler: connection 10.. 63. 163:13378 accepted
 sshd[2129: TLS handshake error 10.. 59. 10:40706:
 scheduler: health check passed backend-2 63ms
[3054: reconciling deployment: 3 replicas ready
[5974: connection 10.. 239. 11:40115 accepted
 systemd: health check backend-4 209ms
 scheduler: TLS handshake error 10.. 128. 31:40135:
 api-server[303]: reconciling deployment: 3 replicas ready
-proxy: health check backend-35 47ms
 ss
```

## code (llmlingua/prompt_compressor.py) @ rate 0.5

### original (first 1200 chars)

```
# Copyright (c) 2023 Microsoft
# Licensed under The MIT License [see LICENSE for details]

import bisect
import copy
import json
import re
import string
from collections import defaultdict
from typing import List, Union

import nltk
import numpy as np
import tiktoken
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoModelForTokenClassification,
    AutoTokenizer,
)

from .utils import (
    TokenClfDataset,
    get_pure_token,
    is_begin_of_new_word,
    process_structured_json_data,
    remove_consecutive_commas,
    replace_added_token,
    seed_everything,
)


class PromptCompressor:
    """
    PromptCompressor is designed for compressing prompts based on a given language model.

    This class initializes with the language model and its configuration, preparing it for prompt compression tasks.
    The PromptCompressor class is versatile and can be adapted for various models and specific requirements in prompt processing.
    Users can specify different model names and configurations as needed for their particular use case.The architecture is
    based on the paper 
```

### compressed (first 1200 chars)

```
Copyright (c 2023 Microsoft
 Licensed MIT License

 import
 copy
 json

 string
 collections defaultdict
 typing, Union

 nltk
 numpy
 tiktoken
 torch
..
 torch.. DataLoader
 transformers
 AutoConfig,
 AutoModelForCausalLM,
 AutoModelForTokenClassification,
 AutoTokenizer,


. utils
 TokenClfDataset,
 get_pure_token,
_new_word,
 process_structured_json_data,
 remove_consecutive_commas,
 replace_added_token,
 seed_everything,



 PromptCompressor:

 compressing prompts language model.

 initializes language model configuration, compression tasks.
 versatile adapted models requirements.
 Users specify model names configurations.
 based paper "LLMLingua: Compressing Prompts Accelerated Inference Large Language Models., Huiqiang,,
 Chin-Yew Lin, Yuqing,. arXiv. 05736.

:
 model_name, language model. Default "NousResearch/Llama-2-7b-hf.
 device_map, device load model,..,. Default.
model_config, dictionary configuration parameters model. Default empty dictionary.
 open_api_config, configuration openai APIs model. empty dictionary.
 use_llmlingua2, llmlingua-2 compressor
 "LLMLingua-2: Data Distillation Efficient Faithful Task-Agnostic Prompt Compression.
, Qianhui, Huiqiang, Menglin, Xuf
```
