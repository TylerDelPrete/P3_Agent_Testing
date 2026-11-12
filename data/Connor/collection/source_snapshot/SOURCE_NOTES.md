# From Component Manipulation to System Compromise: Understanding and Detecting Malicious MCP Servers

## Overview

This repo contains the PoCs which target system compromise by injecting adversarial content into the components of MCP servers, as well as the source code of the detector for malicious servers. The repository is organized as follows:

- `PoCs`: This folder contains the PoCs we constructed.
- `Dataset`: This folder contains the curated dataset we used in the evaluation.
- `Connor`: This folder contains the source code of the detector Connor.

## PoCs

**⚠️ Attention: These PoCs are provided solely for research purposes. Do not use them for malicious activities.**

114 PoCs are organized in six directories: `backdoor_PoC`, `payload_exec_PoC`, `ransomware_PoC`, `reverse_shell_PoC`, `stealing_PoC`, and `sabotaging_PoC`. Each directory contains subdirectories P1-P19, corresponding to different influence paths.

The `external_resources` folder contains the malicious external resources used for payload execution and indirect prompt injection. For quick deployment, you can run the following command in the `external_resources` directory, or set up your own server.

```shell
python -m http.server 8080
```


## Dataset

The `Dataset` folder contains the curated MCP dataset used in our evaluation, organized into two categories:

- **Benign**: Contains legitimate MCP servers that serve as benign samples for evaluation
- **Malicious**: Contains malicious MCP servers used in our study. Note that this folder only includes malicious samples that are separate from the PoCs provided in the `PoCs` folder


## Detector

### Prerequisite

The detector needs [docker](https://www.docker.com/) to run the MCP servers, as the **servers may contain side effects to the system**.

### Setup

Once you have cloned the repo, cd to the directory of `Connor`. 

The implementation targets Python >= 3.11. Install the dependencies with:

```shell
pip install -r requirements.txt
```

Set the [Open Router](https://openrouter.ai/) key in the file `config.py`. The implementation is not restricted to OpenRouter; you can use other providers as it is compatible with the OpenAI API.

```python
OPENROUTER_API_KEY = "your_openrouter_api_key"
```

We release the Docker image at https://doi.org/10.5281/zenodo.18464634, which contains all the necessities for running the detector. Before running the detector, it is recommended to load the image via:

```shell
docker load -i connor_docker.tar
```

### Usage

To run Connor for MCP server security analysis, use the `connor_docker.py` script:

```shell
python connor_docker.py -d /path/to/mcp/server
```

#### Command-line Arguments

- `-d, --mcp-server-dir` (required): Path to the MCP server directory on the host machine
- `-w, --workspace-dir` (optional): Workspace directory for storing analysis results (default: `./mcp_workspace`)
- `-c, --config-file` (optional): Name of the MCP server configuration JSON file (default: `mcp.json`)
- `-l, --language` (optional): Programming language of the MCP server. Options: `python`, `javascript`, `typescript`. If not specified, the language will be auto-detected
- `-t, --timeout` (optional): Execution timeout in seconds (default: 1800s = 30min)
- `-r, --results-file` (optional): Path to the results CSV file. If not provided, results will not be written

#### Example

```shell
python connor_docker.py -d ./my_mcp_server -w ./analysis_results/my_mcp_server -l python -t 600 -r ./analysis_results/results.csv
```

After execution completes, the analysis results will be available in the workspace directory:

- **Logs**: Detailed execution logs are stored in the `log` folder
- **Results**: The detection results are saved in `detection_result.json`. Simplified results will also be provided in the console.

#### ❗️ Requirements for MCP Servers

For Connor to successfully analyze an MCP server, the server directory must meet the following requirements:

- **Source code**: The complete source code of the MCP server must be included in the directory
- **Configuration file**: The directory must contain a configuration file that specifies the server's startup configuration. The default filename is `mcp.json`. If using a different filename, specify it with the `-c` option

## Licensing

- Original source code under `Connor/` is licensed under the Apache License,
  Version 2.0. See `Connor/LICENSE` and `Connor/NOTICE`.
- Original proof-of-concept materials under `PoCs/` are licensed under the
  Apache License, Version 2.0. Copies, adaptations, and publications must retain
  the educational and defensive security research notice in `PoCs/NOTICE`.
- Materials under `Dataset/` originate from third-party projects and are not
  covered by the licenses for `Connor/` or `PoCs/`. Their respective upstream
  licenses and terms apply.

See `LICENSE.md` and `THIRD_PARTY_NOTICES.md` for details.
