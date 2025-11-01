<!DOCTYPE html>
<html>
<head>
    <title>Video Analysis</title>
    <link rel="stylesheet" type="text/css" href="style.css">
</head>
<body>
    <div class="container">
        <h1>Video Analysis</h1>
        <div class="video-container">
            <img id="video-stream" src="">
        </div>
        <div class="controls">
            <form id="video-form">
                <select name="video_file" id="video-file">
                    <?php
                        $videos_dir = 'data/';
                        $videos = glob($videos_dir . '*.{mp4,avi,mov,mkv}', GLOB_BRACE);
                        foreach ($videos as $video) {
                            echo '<option value="' . $video . '">' . basename($video) . '</option>';
                        }
                    ?>
                </select>
                <button type="submit" name="start_analysis">Start Analysis</button>
            </form>
            <div class="action-buttons">
                <button id="save-roi">Save ROI</button>
                <button id="reset-roi">Reset ROI</button>
                <button id="reset-all">Reset All</button>
            </div>
        </div>
    </div>

    <script>
        const videoStream = document.getElementById('video-stream');
        const videoForm = document.getElementById('video-form');

        videoForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const videoFile = document.getElementById('video-file').value;

            // Stop any existing python processes
            await fetch('stop_analysis.php');

            // Start the python script
            const formData = new FormData();
            formData.append('video_file', videoFile);
            await fetch('start_analysis.php', {
                method: 'POST',
                body: formData
            });

            // Poll for the stream to be ready
            const streamUrl = `http://${window.location.hostname}:8080/video_feed`;
            const waitForStream = async () => {
                console.log("Waiting for stream to be ready...");
                while (true) {
                    try {
                        // Use fetch with a timeout. A successful (even if opaque) response
                        // means the server is up.
                        const controller = new AbortController();
                        const timeoutId = setTimeout(() => controller.abort(), 1000);
                        await fetch(streamUrl, { mode: 'no-cors', signal: controller.signal });
                        clearTimeout(timeoutId);
                        console.log("Stream is ready!");
                        return;
                    } catch (error) {
                        // Server not ready yet, wait and retry
                        await new Promise(resolve => setTimeout(resolve, 500));
                    }
                }
            };
            await waitForStream();
            videoStream.src = streamUrl;
        });

        videoStream.addEventListener('click', (e) => {
            const rect = videoStream.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            fetch(`http://${window.location.hostname}:8080/click`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ x: x / (rect.width / 1280), y: y / (rect.height / 960) })
            });
        });

        document.getElementById('save-roi').addEventListener('click', () => {
            fetch(`http://${window.location.hostname}:8080/save_roi`, { method: 'POST' });
        });

        document.getElementById('reset-roi').addEventListener('click', () => {
            fetch(`http://${window.location.hostname}:8080/reset_roi`, { method: 'POST' });
        });

        document.getElementById('reset-all').addEventListener('click', () => {
            fetch(`http://${window.location.hostname}:8080/reset_all`, { method: 'POST' });
        });
    </script>
</body>
</html>