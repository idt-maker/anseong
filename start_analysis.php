<?php
if (isset($_POST['video_file'])) {
    $video_file = $_POST['video_file'];
    // Start the python script in the background
    $command = 'python3 video_analysis.py --video ' . escapeshellarg($video_file) . ' > /dev/null 2>&1 &';
    shell_exec($command);
}
