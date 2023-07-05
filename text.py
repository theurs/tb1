import glob


for filePath in [x for x in glob.glob('*.wav') + glob.glob('*.ogg') if 'temp_tts_file' in x]:
    try:
        os.remove(filePath)
    except:
        print("Error while deleting file : ", filePath)
