# video_compression_automation
Fast way to compress your videos and save enormous amount of space on hard drive using python script and HandBrake CLI commands


## Documentation

### HandBrakeCLI manual test.

Had some problems with the HandBrakeCLI commands working so had to test it manually. I opened up CMD on windows and tried different commands. 

> C:\Downloads>"C:\Program Files\HandBrake\HandBrakeCLI.exe" -i "Fortnite_test.mp4" -o "MyTestVideo_compressed.mp4" --preset Web/Creator 1080p60

Note: The command above did not work because it did not enclose the preset option **Web/Creator 1080p60** in Quotes

> C:\Downloads>"C:\Program Files\HandBrake\HandBrakeCLI.exe" -i "Fortnite_test.mp4" -o "MyTestVideo_compressed.mp4" --preset "Web/Creator 1080p60"

This command's syntax was correct but it could NOT process the file??? I am baffled because the same exact file works in HandBrake GUI. I googled and eventually asked Gemini about it and it said that it could be because the file is somehow not in a correct format and needs 'Remuxing' and FFMPEG library could do the trick. Aarghh, more hassle and steps along the way. Downloaded FFMPEG and begun to start the *Remux* process for the file and then, by accident I noticed as I pressed Tab to get the filename autocompleted on cmd it showed me this: 

> C:\Downloads>"C:\ffmpeg\bin\ffmpeg.exe" -i "Fortnite_test.mp4.mp4" -c copy "Fortnite_test_remuxed.mp4"  

As I have a powerful RTX 4070 GPU, I wanted to take advantage of it and use Hardware NVIDIA encoding (H.265 NVENC). For a test case I compressed a 1,68 Gb game recording down to just under 300 Mb in around 40 seconds. I will take one more test and after I can conclude that it works I will create a script that finds all game recordings in a folder and its subfolders with certain criteria and compresses them to be around 70% smaller in size than the original counterparts.


#### Advanced configs to optimize compression

- Parallel processing
    - NVIDIA Engine paired with RTX 4070 potentially could to 2-4 files at once, which really speeds up the compression operations significantly and I really see no reason NOT to use it.