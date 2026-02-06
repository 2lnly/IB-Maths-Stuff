#!/bin/bash
# Auto-run extraction then classification

cd /home/xiaohe/stuff/claudable/physics_organizer

echo "Waiting for extraction to complete..."
while pgrep -f "python extract_text.py" > /dev/null; do
    sleep 10
done

echo ""
echo "Extraction complete! Starting classification..."
echo ""

# Start classification
python classify.py

echo ""
echo "Pipeline complete!"
