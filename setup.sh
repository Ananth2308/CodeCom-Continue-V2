#!/bin/bash
# Setup script for Dev Agent Proxy on EC2

set -e

echo "=== Dev Agent Proxy Setup ==="

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "Created .env file. Please edit it with your configuration:"
    echo "  nano .env"
    echo ""
    echo "Required settings:"
    echo "  AGENT_VLLM_BASE_URL  - URL to your vLLM instance"
    echo "  AGENT_VLLM_MODEL     - Model name loaded in vLLM"
    echo "  AGENT_WORKSPACE_DIR  - Path to the project you want the agent to work on"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start the proxy:"
echo "  source .venv/bin/activate"
echo "  python run.py"
echo ""
echo "To install as a systemd service:"
echo "  sudo cp deploy/dev-agent-proxy.service /etc/systemd/system/"
echo "  sudo systemctl enable dev-agent-proxy"
echo "  sudo systemctl start dev-agent-proxy"
echo ""
echo "Configure Continue (VS Code) to point to: http://YOUR_EC2_IP:8080/v1"
echo "See deploy/continue-config-example.json for the full config."
