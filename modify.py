from __future__ import print_function
import httplib2
import os
import io
import threading
import time
import concurrent.futures
from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from apiclient.http import MediaFileUpload, MediaIoBaseDownload
from pathlib import Path
import PyPDF2
from pdfminer.high_level import extract_text

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None

SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = 'credentials.json'
APPLICATION_NAME = 'Drive API Python Quickstart'
THREADS = 20
srt_file_list = {}

def get_credentials():
    credential_path = os.path.join("./", 'token.json')
    store = Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
        flow.user_agent = APPLICATION_NAME
        if flags:
            credentials = tools.run_flow(flow, store, flags)
        else:
            credentials = tools.run(flow, store)
        print('Storing credentials to ' + credential_path)
    return credentials

total_images = 0
completed_scans = 0
scan_lock = threading.Lock()

def main():
    global completed_scans, total_images
    credentials = get_credentials()
    http = credentials.authorize(httplib2.Http())
    service = discovery.build('drive', 'v3', http=http)

    current_directory = Path(Path.cwd())
    images_dir = Path(f'{current_directory}/images')
    raw_texts_dir = Path(f'{current_directory}/raw_texts')
    texts_dir = Path(f'{current_directory}/texts')
    srt_file = open(Path(f'{current_directory}/subtitle_output.txt'), 'a', encoding='utf-8')
    line = 1
    
    pdf_file_path = Path(f'{current_directory}/input.pdf')
    output_text_file_path = Path(f'{current_directory}/output.txt')

    pdf_to_text(pdf_file_path, output_text_file_path)



    if not images_dir.exists():
        images_dir.mkdir()
        print('Images folder is empty.')
        exit()

    if not raw_texts_dir.exists():
        raw_texts_dir.mkdir()
    if not texts_dir.exists():
        texts_dir.mkdir()

    image_extensions = ('*.jpeg', '*.jpg', '*.png', '*.bmp', '*.gif')
    images = []
    for extension in image_extensions:
        images.extend(list(Path(f'{current_directory}/images').rglob(extension)))

    total_images = len(images)

    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS) as executor:
        future_to_image = {executor.submit(ocr_image, image, index+1, credentials, current_directory): image for index, image in enumerate(images)}
        for future in concurrent.futures.as_completed(future_to_image):
            image = future_to_image[future]
            try:
                future.result()
            except Exception as exc:
                print(f"{image} generated an exception: {exc}")
            else:
                with scan_lock:
                    completed_scans += 1
                    available = total_images - completed_scans
                    print(f"Available = {available} Scan = {completed_scans} Total = {total_images}", end="\r")

    print()  # To move to the next line after the final update
    for i in sorted(srt_file_list):
        srt_file.writelines(srt_file_list[i])
    srt_file.close()

#pdf function for pdf scan 


def pdf_to_text(pdf_file_path, output_text_file_path):
    try:
        # Check if the input file is encrypted
        with open(pdf_file_path, 'rb') as file:
            reader = PyPDF2.PdfFileReader(file)
            if reader.isEncrypted:
                print("The input PDF file is encrypted. Cannot extract text.")
                return

        # Extract text from the input PDF file
        extracted_text = extract_text(pdf_file_path)

        # Write the extracted text to the output text file
        with open(output_text_file_path, 'w', encoding='utf-8') as output_file:
            output_file.write(extracted_text)
    except Exception as e:
        print(f"Error processing {pdf_file_path}: {e}")




#this is a function for scan images 
def ocr_image(image, line, credentials, current_directory):
    tries = 0
    while True:
        try:
            http = credentials.authorize(httplib2.Http())
            service = discovery.build('drive', 'v3', http=http)
            imgfile = str(image.absolute())
            imgname = str(image.name)
            raw_txtfile = f'{current_directory}/raw_texts/{imgname[:-5]}.txt'
            txtfile = f'{current_directory}/texts/{imgname[:-5]}.txt'

            mime = 'application/vnd.google-apps.document'
            res = service.files().create(
                body={
                    'name': imgname,
                    'mimeType': mime
                },
                media_body=MediaFileUpload(imgfile, mimetype=mime, resumable=True)
            ).execute()
            downloader = MediaIoBaseDownload(
                io.FileIO(raw_txtfile, 'wb'),
                service.files().export_media(fileId=res['id'], mimeType="text/plain")
            )
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            service.files().delete(fileId=res['id']).execute()

            with open(raw_txtfile, 'r', encoding='utf-8') as raw_text_file:
                text_content = raw_text_file.read()

            text_content = text_content.split('\n')
            text_content = ''.join(text_content[2:])

            with open(txtfile, 'w', encoding='utf-8') as text_file:
                text_file.write(text_content)

            try:
                start_hour = imgname.split('_')[0][:2]
                start_min = imgname.split('_')[1][:2]
                start_sec = imgname.split('_')[2][:2]
                start_micro = imgname.split('_')[3][:3]

                end_hour = imgname.split('__')[1].split('_')[0][:2]
                end_min = imgname.split('__')[1].split('_')[1][:2]
                end_sec = imgname.split('__')[1].split('_')[2][:2]
                end_micro = imgname.split('__')[1].split('_')[3][:3]

            except IndexError:
                print(f"Error processing {imgname}: Filename format is incorrect. Please ensure the correct format is used.")
                return

            start_time = f'{start_hour}:{start_min}:{start_sec},{start_micro}'
            end_time = f'{end_hour}:{end_min}:{end_sec},{end_micro}'
            srt_file_list[line] = [
                f'{line}\n',
                f'{start_time} --> {end_time}\n',
                f'{text_content}\n\n',
                ''
            ]
            break
        except:
            tries += 1
            if tries > 5:
                raise
            continue


if __name__ == '__main__':
    main()
