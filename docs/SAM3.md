# SAM 3.1 proposal helper

SAM 3.1 is optional. It is a second way to propose robot boxes for human review; it is **not**
the deployed detector and it does not replace RF-DETR.

```text
extracted full frame
  -> SAM 3.1 text prompt: "FRC competition robot"
  -> sam3-proposals.jsonl (unreviewed boxes)
  -> compare/review in Roboflow
  -> reviewed robot boxes
  -> RF-DETR training
  -> C++ analysis uses the RF-DETR ONNX model
```

SAM gets no access to the database, website, or live-match results. The tool only reads an
existing collection's JPEG frames and writes a proposal file next to them. It never overwrites
`model-proposals.jsonl` or `model-consensus.jsonl`, so the three-Ollama-model measurements stay
meaningful.

## Robert's one-time setup

Do this on Robert's Windows desktop with the RTX 3060, not Justin's AMD PC or a Mac. Keep it in a
separate environment; **do not install SAM into `ingest\.venv`**.

Meta's current prerequisites are Python 3.12+, PyTorch 2.7+, and CUDA 12.6+. SAM 3.1 checkpoints
also require an approved Hugging Face account and login. Follow Meta's checkpoint access terms and
SAM License; do not commit either checkpoint files or tokens.

```powershell
# anywhere on Robert's CUDA PC
mkdir C:\FRC-SAM3
cd C:\FRC-SAM3
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
git clone https://github.com/facebookresearch/sam3.git
.\.venv\Scripts\python -m pip install -e .\sam3
.\.venv\Scripts\python -m pip install huggingface_hub
.\.venv\Scripts\hf auth login
```

The final command opens a prompt for Robert's own Hugging Face access token. That token stays on
his PC; never put it in Git, Discord, a `.env` committed to the repo, or chat.

## Run a small test first

After a normal `extract` command has created a collection, use Robert's SAM Python executable from
the project root:

```powershell
# in: C:\Coding Stuff\Robotics\FRC-Auto-Scouting
C:\FRC-SAM3\.venv\Scripts\python.exe -m ingest.collection.cli sam3-propose `
  --collection data\collections\<collection-id> `
  --limit 10
```

This writes `sam3-proposals.jsonl`. It is marked `status: proposed` and
`human_review_required: true`, just like the existing local-model output. Review whether the
boxes are actually FRC robots and whether they tightly cover the whole robot. If the prompt is too
broad, try a different wording without changing any training labels:

```powershell
C:\FRC-SAM3\.venv\Scripts\python.exe -m ingest.collection.cli sam3-propose `
  --collection data\collections\<collection-id> `
  --prompt "competition robot on an FRC field" `
  --limit 10 --force
```

Only after reviewers accept boxes do they become RF-DETR training labels. The current repository
does not send SAM's file directly to Roboflow or train from it automatically; that separation is
intentional. It prevents an untested foundation model from teaching RF-DETR its mistakes.

## What comes later

The first integration uses SAM's documented image text-prompt API because it is cheap to evaluate
on a small collection and produces the same full-frame boxes RF-DETR needs. If it proves helpful,
the next step is a separate video-tracking experiment using SAM 3.1 Object Multiplex to propagate
reviewed robot prompts across nearby frames. That remains an experiment until it has been checked
against human labels.

Sources: [SAM 3 repository](https://github.com/facebookresearch/sam3), [SAM 3.1 release notes](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md), and [SAM License](https://github.com/facebookresearch/sam3/blob/main/LICENSE).
