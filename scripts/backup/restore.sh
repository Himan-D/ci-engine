#!/bin/bash
set -euo pipefail

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $0 <backup_type> [options]

Backup types:
  database    Restore database from backup
  secrets     Restore Kubernetes secrets
  all         Restore everything

Options:
  -t, --timestamp  Specify backup timestamp (YYYYMMDD_HHMMSS)
  -f, --file       Specify backup file path (overrides timestamp)
  -d, --dry-run    Show what would be restored without applying

Examples:
  $0 database -t 20240315_143000
  $0 secrets -f /backups/secrets_20240315_143000.enc
  $0 all -t 20240315_143000 --dry-run
EOF
}

restore_database() {
    local backup_file="$1"
    local dry_run="$2"
    local db_name="${DATABASE_URL##*/}"
    
    log "Restoring database from $backup_file..."
    
    if [[ -n "$dry_run" ]]; then
        log "[DRY RUN] Would restore database $db_name"
        return 0
    fi
    
    openssl enc -aes-256-cbc -d -pbkdf2 -pass "pass:$ENCRYPTION_KEY" \
        -in "$backup_file" | \
        gunzip | \
        psql -d "$db_name"
    
    log "Database restored successfully"
}

restore_secrets() {
    local backup_file="$1"
    local dry_run="$2"
    
    log "Restoring secrets from $backup_file..."
    
    local temp_file
    temp_file="$(mktemp)"
    trap "rm -f $temp_file" EXIT
    
    openssl enc -aes-256-cbc -d -pbkdf2 -pass "pass:$ENCRYPTION_KEY" \
        -in "$backup_file" \
        -out "$temp_file"
    
    if [[ -n "$dry_run" ]]; then
        log "[DRY RUN] Would apply secrets:"
        cat "$temp_file"
        return 0
    fi
    
    while read -r key value; do
        echo "$value" | base64 -d | \
            kubectl create secret generic "ci-engine-secrets" \
            --from-literal="$key=-" \
            --dry-run=client -o json | \
            kubectl apply -f -
    done < "$temp_file"
    
    log "Secrets restored successfully"
}

main() {
    local backup_type="${1:-}"
    local timestamp=""
    local file_path=""
    local dry_run=""
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -t|--timestamp)
                timestamp="$2"
                shift 2
                ;;
            -f|--file)
                file_path="$2"
                shift 2
                ;;
            -d|--dry-run)
                dry_run="1"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                shift
                ;;
        esac
    done
    
    local S3_BUCKET="${S3_BACKUP_BUCKET:-ci-engine-backups}"
    local BACKUP_DIR="${BACKUP_DIR:-/backups}"
    local ENCRYPTION_KEY="${ENCRYPTION_KEY:-}"
    
    if [[ -z "$backup_type" ]]; then
        usage
        exit 1
    fi
    
    case "$backup_type" in
        database)
            local db_file="${file_path:-${BACKUP_DIR}/database_${timestamp}.sql.gz.enc}"
            if [[ ! -f "$db_file" ]]; then
                db_file="/tmp/database_$$.sql.gz.enc"
                aws s3 cp "s3://${S3_BUCKET}/backups/database_${timestamp}.sql.gz.enc" "$db_file"
            fi
            restore_database "$db_file" "$dry_run"
            ;;
        secrets)
            local sec_file="${file_path:-${BACKUP_DIR}/secrets_${timestamp}.enc}"
            if [[ ! -f "$sec_file" ]]; then
                sec_file="/tmp/secrets_$$.enc"
                aws s3 cp "s3://${S3_BUCKET}/backups/secrets_${timestamp}.enc" "$sec_file"
            fi
            restore_secrets "$sec_file" "$dry_run"
            ;;
        all)
            main database "$@"
            main secrets "$@"
            ;;
        *)
            error "Unknown backup type: $backup_type"
            ;;
    esac
}

main "$@"