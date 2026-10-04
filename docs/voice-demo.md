# Voice demo (optional, needs an AWS deployment)

Not part of `docker compose up`. It needs the AWS deployment described in the [README](../README.md#on-aws) and Bedrock access to
**Amazon Nova 2 Sonic** (`amazon.nova-2-sonic-v1:0`, us-east-1 or three other regions).

The web app serves a page `/voice` with a microphone button. Your voice goes to Nova 2 Sonic, which calls the same seven tools through the
AgentCore Gateway with the diner's own token, so every rule of the server applies. The assistant holds a table, reads the details back, and
books only after you say yes.

## Run it
1. Sign in to AWS on your machine (the profile that owns the deployment) and install the optional extra:
   `pip install -c constraints.txt -e ".[web,sim,voice]"` (Python 3.12).
2. Start the web app with the script for your shell. It reads every setting from the deployed stacks (CloudFormation outputs and the Cognito
   client) and then runs `python -m web`; nothing account-specific is stored in the repository. Run it from the repository root, with the
   Python environment that has the extras installed:

   ```powershell
   # Windows PowerShell
   aws login --profile <aws-profile>
   .\scripts\voice_demo.ps1 -Profile <aws-profile>
   ```

   ```bash
   # macOS, Linux, Git Bash
   aws login --profile <aws-profile>
   AWS_PROFILE=<aws-profile> bash scripts/voice_demo.sh
   ```

   Add `-NoStart` (PowerShell) or `--no-start` (bash) to only check that the settings can be read. Pass `-Python <path>` or set
   `PYTHON=<path>` if `python` on your path is not the environment you installed into. Use the profile that owns the deployment, never a
   root user.
3. Open http://localhost:8080/voice and sign in as `diner-alice` / `alice-dev-pass` (the Cognito users have the same names and passwords as
   the local ones). Press **Start the call**, allow the microphone and say: *"Book a table at Luna Trattoria for two people tomorrow at seven
   in the evening."* Use headphones, or the speaker's sound goes back into the microphone. When the assistant asks "Shall I book it?", say
   *"Yes, please."* The page shows what you said, what it said and each tool call behind it. Stop with **End the call**; a call lasts at most
   seven minutes.

## Cost
A whole booking conversation used about 3,300 tokens in and 1,400 out. Speech tokens cost $3 and $12 per million in us-east-1 (2026-09-30), so
under two cents. `VOICE_REGION` and `VOICE_NAME` change the region and the voice. If the call stops at the start, check that your account can
use Nova 2 Sonic in that region.

## Test without a person
`pytest -m aws tests/aws/test_voice.py` plays two recorded sentences into the page's endpoint and checks that the assistant asks before
booking and books after the yes.
