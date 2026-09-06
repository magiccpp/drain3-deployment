| model | document | target rate | tokens before | tokens after | kept | seconds | input tok/s |
|---|---|---|---|---|---|---|---|
| xlm-roberta-large | docs/markdown (LLMLingua README) | 0.33 | 5202 | 1609 | 30.9% | 0.35 | 14930 |
| xlm-roberta-large | docs/markdown (LLMLingua README) | 0.50 | 5202 | 2621 | 50.4% | 0.34 | 15488 |
| xlm-roberta-large | docs/markdown (LLMLingua README) | 0.70 | 5202 | 3839 | 73.8% | 0.34 | 15413 |
| xlm-roberta-large | prose (Wikipedia: Transformer_(deep_learning_architecture)) | 0.33 | 22429 | 4299 | 19.2% | 1.39 | 16101 |
| xlm-roberta-large | prose (Wikipedia: Transformer_(deep_learning_architecture)) | 0.50 | 22429 | 7955 | 35.5% | 1.37 | 16416 |
| xlm-roberta-large | prose (Wikipedia: Transformer_(deep_learning_architecture)) | 0.70 | 22429 | 12291 | 54.8% | 1.46 | 15331 |
| xlm-roberta-large | prose (Wikipedia: Large_language_model) | 0.33 | 11036 | 3702 | 33.5% | 0.75 | 14725 |
| xlm-roberta-large | prose (Wikipedia: Large_language_model) | 0.50 | 11036 | 5561 | 50.4% | 0.73 | 15048 |
| xlm-roberta-large | prose (Wikipedia: Large_language_model) | 0.70 | 11036 | 7688 | 69.7% | 0.73 | 15097 |
| xlm-roberta-large | prose (Wikipedia: Graphics_processing_unit) | 0.33 | 5803 | 2122 | 36.6% | 0.39 | 15016 |
| xlm-roberta-large | prose (Wikipedia: Graphics_processing_unit) | 0.50 | 5803 | 3113 | 53.6% | 0.41 | 14222 |
| xlm-roberta-large | prose (Wikipedia: Graphics_processing_unit) | 0.70 | 5803 | 4231 | 72.9% | 0.39 | 14896 |
| xlm-roberta-large | prose (Wikipedia: Attention_(machine_learning)) | 0.33 | 4946 | 925 | 18.7% | 0.32 | 15280 |
| xlm-roberta-large | prose (Wikipedia: Attention_(machine_learning)) | 0.50 | 4946 | 1732 | 35.0% | 0.33 | 15030 |
| xlm-roberta-large | prose (Wikipedia: Attention_(machine_learning)) | 0.70 | 4946 | 2694 | 54.5% | 0.33 | 15143 |
| xlm-roberta-large | logs (synthetic server log) | 0.33 | 25858 | 6858 | 26.5% | 1.31 | 19769 |
| xlm-roberta-large | logs (synthetic server log) | 0.50 | 25858 | 11326 | 43.8% | 1.31 | 19757 |
| xlm-roberta-large | logs (synthetic server log) | 0.70 | 25858 | 17083 | 66.1% | 1.31 | 19691 |
| xlm-roberta-large | code (llmlingua/prompt_compressor.py) | 0.33 | 8101 | 2680 | 33.1% | 0.60 | 13546 |
| xlm-roberta-large | code (llmlingua/prompt_compressor.py) | 0.50 | 8101 | 4037 | 49.8% | 0.59 | 13801 |
| xlm-roberta-large | code (llmlingua/prompt_compressor.py) | 0.70 | 8101 | 5447 | 67.2% | 0.60 | 13434 |
| xlm-roberta-large | long prose (all Wikipedia articles concatenated) | 0.33 | 44216 | 11075 | 25.0% | 2.87 | 15409 |
| xlm-roberta-large | long prose (all Wikipedia articles concatenated) | 0.50 | 44216 | 18397 | 41.6% | 2.95 | 14970 |
| xlm-roberta-large | long prose (all Wikipedia articles concatenated) | 0.70 | 44216 | 26938 | 60.9% | 2.96 | 14932 |
| bert-base-multilingual-cased | docs/markdown (LLMLingua README) | 0.33 | 5202 | 1755 | 33.7% | 0.17 | 29988 |
| bert-base-multilingual-cased | docs/markdown (LLMLingua README) | 0.50 | 5202 | 2823 | 54.3% | 0.16 | 32206 |
| bert-base-multilingual-cased | docs/markdown (LLMLingua README) | 0.70 | 5202 | 4069 | 78.2% | 0.16 | 31925 |
| bert-base-multilingual-cased | prose (Wikipedia: Transformer_(deep_learning_architecture)) | 0.33 | 22429 | 5410 | 24.1% | 0.65 | 34409 |
| bert-base-multilingual-cased | prose (Wikipedia: Transformer_(deep_learning_architecture)) | 0.50 | 22429 | 8673 | 38.7% | 0.64 | 35024 |
| bert-base-multilingual-cased | prose (Wikipedia: Transformer_(deep_learning_architecture)) | 0.70 | 22429 | 13705 | 61.1% | 0.65 | 34636 |
| bert-base-multilingual-cased | prose (Wikipedia: Large_language_model) | 0.33 | 11036 | 3379 | 30.6% | 0.32 | 34266 |
| bert-base-multilingual-cased | prose (Wikipedia: Large_language_model) | 0.50 | 11036 | 5395 | 48.9% | 0.32 | 34010 |
| bert-base-multilingual-cased | prose (Wikipedia: Large_language_model) | 0.70 | 11036 | 7729 | 70.0% | 0.33 | 33732 |
| bert-base-multilingual-cased | prose (Wikipedia: Graphics_processing_unit) | 0.33 | 5803 | 1860 | 32.1% | 0.17 | 35010 |
| bert-base-multilingual-cased | prose (Wikipedia: Graphics_processing_unit) | 0.50 | 5803 | 2928 | 50.5% | 0.17 | 34614 |
| bert-base-multilingual-cased | prose (Wikipedia: Graphics_processing_unit) | 0.70 | 5803 | 4109 | 70.8% | 0.17 | 33737 |
| bert-base-multilingual-cased | prose (Wikipedia: Attention_(machine_learning)) | 0.33 | 4946 | 1195 | 24.2% | 0.15 | 33113 |
| bert-base-multilingual-cased | prose (Wikipedia: Attention_(machine_learning)) | 0.50 | 4946 | 1866 | 37.7% | 0.15 | 32218 |
| bert-base-multilingual-cased | prose (Wikipedia: Attention_(machine_learning)) | 0.70 | 4946 | 3013 | 60.9% | 0.15 | 32635 |
| bert-base-multilingual-cased | logs (synthetic server log) | 0.33 | 25858 | 10080 | 39.0% | 0.67 | 38738 |
| bert-base-multilingual-cased | logs (synthetic server log) | 0.50 | 25858 | 16173 | 62.5% | 0.66 | 38955 |
| bert-base-multilingual-cased | logs (synthetic server log) | 0.70 | 25858 | 22770 | 88.1% | 0.67 | 38634 |
| bert-base-multilingual-cased | code (llmlingua/prompt_compressor.py) | 0.33 | 8101 | 2857 | 35.3% | 0.26 | 30776 |
| bert-base-multilingual-cased | code (llmlingua/prompt_compressor.py) | 0.50 | 8101 | 4607 | 56.9% | 0.26 | 30786 |
| bert-base-multilingual-cased | code (llmlingua/prompt_compressor.py) | 0.70 | 8101 | 6606 | 81.5% | 0.27 | 30114 |
| bert-base-multilingual-cased | long prose (all Wikipedia articles concatenated) | 0.33 | 44216 | 11826 | 26.7% | 1.25 | 35342 |
| bert-base-multilingual-cased | long prose (all Wikipedia articles concatenated) | 0.50 | 44216 | 18821 | 42.6% | 1.45 | 30451 |
| bert-base-multilingual-cased | long prose (all Wikipedia articles concatenated) | 0.70 | 44216 | 28541 | 64.5% | 1.28 | 34621 |