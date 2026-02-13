#!/bin/bash
# Restore script for backup 20260213_190637
# This will restore practice folders, Physics Flattened, and JSON files

BACKUP_DIR="/home/xiaohe/stuff/claudable/backups/20260213_190637"
TARGET_DIR="/home/xiaohe/stuff/claudable"

echo "=========================================="
echo "RESTORE FROM BACKUP: 20260213_190637"
echo "=========================================="
echo ""
echo "This will OVERWRITE the following:"
echo "  - $TARGET_DIR/practice/"
echo "  - $TARGET_DIR/Physics Flattened/"
echo "  - $TARGET_DIR/data/*.json"
echo ""
read -p "Are you sure you want to restore? Type 'yes' to continue: " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled."
    exit 1
fi

echo ""
echo "Starting restore..."

# Restore practice folder
echo "Restoring practice folder..."
rm -rf "$TARGET_DIR/practice"
cp -r "$BACKUP_DIR/practice" "$TARGET_DIR/"

# Restore Physics Flattened folder
echo "Restoring Physics Flattened folder..."
rm -rf "$TARGET_DIR/Physics Flattened"
cp -r "$BACKUP_DIR/Physics Flattened" "$TARGET_DIR/"

# Restore JSON files
echo "Restoring JSON files..."
cp "$BACKUP_DIR"/*.json "$TARGET_DIR/data/"

echo ""
echo "=========================================="
echo "Restore complete!"
echo "=========================================="
echo ""
echo "Restored:"
echo "  ✓ practice/"
echo "  ✓ Physics Flattened/"
echo "  ✓ data/*.json"
