# PandasPlotBench Evaluation Framework

Evaluation scripts for VisCoder based on [PandasPlotBench](https://github.com/JetBrains-Research/PandasPlotBench) with **self-debug evaluation mode** extension.

## 🚀 Quick Start

### Setup
```bash
conda create -n pandasplotbench python=3.10 -y
conda activate pandasplotbench

cd PandasPlotBench
pip install -r requirements.txt
```

### Basic Usage

#### Run Benchmark
The main entry point for running evaluations is `run_benchmark.py`. Key parameters for the `run_benchmark` method include:
- **reuse_results**: If `True`, reuses existing results without generating new plots.
- **only_stats**: If `True`, only calculates statistics without running the full benchmark.
- **skip_score**: If `True`, skips the scoring steps.

Example command:
```bash
python run_benchmark.py --limit=10
```

The `limit` parameter can be used to control the evaluation scope:
- **Integer**: e.g., `10` to randomly select 10 items for evaluation.
- **List**: e.g., `[0,1,2,3,4,5,6,7]` to evaluate only the specified item IDs.
- **None**: Evaluate all items without limitation.

**Recommendation**: Initially, you can skip the scoring step by using the `--skip_score=True` option. This allows you to quickly generate and review the output in the form of Jupyter Notebook files and results JSON files. If you are only interested in obtaining the execution pass rate, you can choose to skip the scoring to avoid the high cost associated with using the 4o judge.

#### Configuration
Key configuration values are set in the YAML files:
- **run_mode**: Determines the evaluation mode (`normal` or `self_debug`).
- **top_k**: Specifies the number of top attempts to consider in self-debug mode.
- **model**: Defines the model to be used for code generation.
- **plotting_lib**: Specifies the plotting library to use (e.g., `matplotlib`, `seaborn`, `plotly`).

Key config files in `configs/`:
- `config_single_run.yaml`: Default configuration for single run
- `config_self_debug_viscoder.yaml`: Self-debug mode configuration

## 📁 Key Files
```bash
── configs/ # Configuration files
├── plotting_benchmark/
│ ├── benchmark.py # Main benchmark class
│ ├── vis_generator.py # Plot execution
│ ├── vis_judge.py # Scoring
│ └── debug_utils.py # Self-debug utilities
│
├── run_benchmark.py # Standard evaluation entry
├── batch_eval_run.py # Batch processing
│
├── launch_normal_eval.sh # Normal mode batch processing script
└── launch_self_debug_eval.sh # Self-debug mode batch processing script
```

## LangSmith 上传

如果需要把未训练模型的 baseline 上传到 LangSmith，使用
`PandasPlotBench/run_eval_and_upload_langsmith.py`。

当前脚本会：
- 启动时自动尝试读取 `PandasPlotBench/.env`、`eval/.env` 和仓库根 `conf/.env`
- 默认在常规运行中计算 `codebert` 代码相似度
- 只有 `visual` 模式才会额外计算图像/任务相似度
- `codebert` 可通过环境变量 `PLOT_BENCH_CODEBERT_DEVICE` 指定设备，例如 `cuda:1`
- 只自动选择主结果文件，不会误选 `.visual`、`.codebert` 或 `.stats` 衍生文件
- 先把 bench 样本 upsert 到 LangSmith Dataset examples
- 再为每个 case 创建绑定 `reference_example_id` 的 experiment run
- 返回可直接打开的 dataset compare URL，便于在 `Experiments` 中查看 baseline 与具体 case

## Running Models

- **Single Model**: Configure `config_single_run.yaml` and run:
  ```bash
  python run_benchmark.py
  ```

- **Multiple Models**: Use the provided shell scripts for batch processing:
  ```bash
  bash launch_normal_eval.sh
  bash launch_self_debug_eval.sh
  ```

## 📈 Output

- **`eval_results/`**: Main directory for evaluation results.
  - `results_{model}_{library}.json`: Detailed evaluation results for each model and library combination.
  - `benchmark_stat.jsonl`: Summary statistics for each benchmark run.
  - `{error_rate_file}.json`: Execution error statistics for each model and library.

- **`debug_results/`**: Contains detailed self-debug attempts in Jupyter Notebook format, documenting each step and result of the self-debugging process.

- **`logs/`**: Logs of the evaluation process.

## Execution Pass Rate

To print the execution success rates from the evaluation results, use the `print_exec_pass.py` script. You can specify an input JSON file and optionally filter results by specific plotting libraries.

Example usage:
- **All libraries**:
  ```bash
  python print_exec_pass.py eval_results/single_run_test.json
  ```

- **Specific library (e.g., matplotlib)**:
  ```bash
  python print_exec_pass.py eval_results/single_run_test.json --libs matplotlib
  ```

This will output the execution success rates in a markdown table format for easy review.

## Acknowledgments

This evaluation framework is built upon the [PandasPlotBench](https://github.com/JetBrains-Research/PandasPlotBench) framework, which is licensed under the Apache License 2.0. We have extended its capabilities with a self-debug evaluation mode to enhance the assessment of LLM visualization code generation and error correction abilities.

For more details on the original framework and its licensing, please refer to the [PandasPlotBench repository](https://github.com/JetBrains-Research/PandasPlotBench).
