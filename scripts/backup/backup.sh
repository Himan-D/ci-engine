#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
DATE="$(date +%Y%m%d_%H%M%S)"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

S3_BUCKET="${S3_BACKUP_BUCKET:-ci-engine-backups}"
DATABASE_URL="${DATABASE_URL:-}"
ENCRYPTION_KEY="${ENCRYPTION_KEY:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
    exit 1
}

backup_database() {
    local db_backup_file="${BACKUP_DIR}/database_${DATE}.sql.gz.enc"
    log "Backing up database..."
    
    if [[ -z "$DATABASE_URL" ]]; then
        error "DATABASE_URL not set"
    fi
    
    if [[ "$DATABASE_URL" == postgresql://* ]]; then
        export PGPASSWORD="${DATABASE_URL#*@*:*/}"
        local db_name="${DATABASE_URL##*/}"
        local host_port="${DATABASE_URL#postgresql://}"
        local host="${host_port%%/*}"
        
        pg_dump -h "${host%:*}" -p "${host#*:}" -U postgres -d "$db_name" | \
            gzip | \
            openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:$ENCRYPTION_KEY" \
            > "$db_backup_file"
        
        log "Database backup saved to $db_backup_file"
    else
        error "Unsupported database type"
    fi
    
    echo "$db_backup_file"
}

backup_secrets() {
    local secrets_file="${BACKUP_DIR}/secrets_${DATE}.enc"
    log "Backing up secrets..."
    
    kubectl get secret ci-engine-secrets -o json | \
        jq -r '.data | to_entries[] | "\(.key) \(.value)"' | \
        openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:$ENCRYPTION_KEY" \
        > "$secrets_file"
    
    log "Secrets backup saved to $secrets_file"
    echo "$secrets_file"
}

backup_s3_metadata() {
    local metadata_file="${BACKUP_DIR}/s3_metadata_${DATE}.json"
    log "Backing up S3 metadata..."
    
    aws s3api list-objects-v2 --bucket "$S3_BUCKET" \
        --query 'Contents[].{Key: Key, Size: Size, LastModified: LastModified}' \
        > "$metadata_file"
    
    log "S3 metadata backup saved to $metadata_file"
    echo "$metadata_file"
}

upload_to_s3() {
    local file="$1"
    local s3_key="backups/$(basename "$file")"
    
    log "Uploading $file to S3..."
    aws s3 cp "$file" "s3://${S3_BUCKET}/${s3_key}"
    
    echo "s3://${S3_BUCKET}/${s3_key}"
}

cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."
    
    find "$BACKUP_DIR" -type f -mtime "+$RETENTION_DAYS" -delete || true
    
    if [[ -n "$S3_BUCKET" ]]; then
        aws s3 ls "s3://${S3_BUCKET}/backups/" | \
            while read -r date time size key; do
                local file_date
                file_date="$(echo "$key" | grep -oP '\d{8}_\d{6}' || true)"
                if [[ -n "$file_date" ]]; then
                    local file_epoch
                    file_epoch="$(date -d "${file_date:0:8} ${file_date:9:6}" +%s || true)"
                    local threshold_epoch
                    threshold_epoch="$(date -d "$RETENTION_DAYS days ago" +%s || true)"
                    if [[ -n "$file_epoch" && -n "$threshold_epoch" && "$file_epoch" -lt "$threshold_epoch" ]]; then
                        log "Deleting old S3 backup: $key"
                        aws s3 rm "s3://${S3_BUCKET}/backups/$key"
                    fi
                fi
            done
    fi
}

main() {
    log "Starting backup..."
    
    mkdir -p "$BACKUP_DIR"
    
    local db_backup secrets_backup metadata_backup
    db_backup="$(backup_database)"
    upload_to_s3 "$db_backup"
    
    secrets_backup="$(backup_secrets)"
    upload_to_s3 "$secrets_backup"
    
    metadata_backup="$(backup_s3_metadata)"
    upload_to_s3 "$metadata_backup"
    
    cleanup_old_backups
    
    log "Backup completed successfully"
    log "Files:"
    log "  - $db_backup"
    log "  - $secrets_backup"
    log "  - $metadata_backup"
}

main "$@"