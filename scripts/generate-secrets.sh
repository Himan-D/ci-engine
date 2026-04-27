#!/bin/bash
# =============================================================================
# CI Engine - Secret Generator Script
# =============================================================================
# Generates secure random secrets for production deployment
# 
# Usage:
#   chmod +x scripts/generate-secrets.sh
#   ./scripts/generate-secrets.sh
# 
# Output:
#   Copy the generated values to your .env file
# =============================================================================

set -e

echo "=============================================="
echo "CI Engine - Production Secret Generator"
echo "=============================================="
echo ""

# Check Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required"
    exit 1
fi

# Generate Fernet key
echo "Generating Fernet key (for secret encryption)..."
FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "CI_ENGINE_FERNET_KEY=$FERNET_KEY"
echo ""

# Generate JWT secret
echo "Generating JWT secret (for authentication)..."
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "CI_ENGINE_JWT_SECRET_KEY=$JWT_SECRET"
echo ""

# Generate database password
echo "Generating database password..."
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
echo "POSTGRES_PASSWORD=$DB_PASSWORD"
echo ""

# Generate Redis password
echo "Generating Redis password..."
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
echo "REDIS_PASSWORD=$REDIS_PASSWORD"
echo ""

# Generate agent token
echo "Generating agent token..."
AGENT_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
echo "CI_AGENT_TOKEN=$AGENT_TOKEN"
echo ""

echo "=============================================="
echo "Secrets Generated Successfully!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Copy these values to your .env file"
echo "2. Or run: ./scripts/generate-secrets.sh >> .env"
echo ""
echo "Example .env entry:"
echo "CI_ENGINE_FERNET_KEY=$FERNET_KEY"
echo "CI_ENGINE_JWT_SECRET_KEY=$JWT_SECRET"
echo "POSTGRES_PASSWORD=$DB_PASSWORD"
echo "REDIS_PASSWORD=$REDIS_PASSWORD"
