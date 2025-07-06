
import os
from datetime import timedelta
import shutil
import subprocess
import csv
import logging
from datetime import datetime

import cv2
import mediapipe as mp
from deepface import DeepFace
from moviepy.editor import VideoFileClip
import boto3
from decouple import config

# Nome do arquivo CSV
CSV_FILE = 'links.csv'  # ajuste para o nome do seu arquivo
DOWNLOADS_PATH = 'downloads'
S3_BUCKET_PARTS = 'pregnants-parts'

# === Configuração de Logging ===

# Cria diretório de logs (se não existir)
os.makedirs("logs", exist_ok=True)

# Gera nome do arquivo de log com data e hora atual
log_filename = datetime.now().strftime("logs/%Y-%m-%d_%H-%M-%S.log")

# Configuração de logging com arquivo separado por execução
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_filename, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ],
    force=True 
)

def extract_frames_with_timestamps(video_path, output_folder="frames", interval_sec=1):
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    os.makedirs(output_folder, exist_ok=True)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Error opening video: {f'{output_folder}/{video_path}'}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    logging.info(f"Extracting frames every {interval_sec} seconds...")
    logging.info(f"Summary: {fps:.2f} FPS | {total_frames} frames | {duration_sec:.2f} seconds")

    frame_count = 0
    saved_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        current_time_sec = frame_count / fps
        
        # Verifica se é o momento de extrair (a cada X segundos)
        if frame_count % int(fps * interval_sec) == 0:
            # Formata o timestamp como HH:MM:SS.mmm
            timestamp = str(timedelta(seconds=current_time_sec))
            if len(timestamp.split(':')[0]) == 1:  # Verifica se horas tem apenas 1 dígito
                timestamp = '0' + timestamp
            
            # Nome do arquivo com timestamp
            filename = f"frame_{timestamp.replace(':', '-')}-{saved_count}.jpg"
            output_path = os.path.join(output_folder, filename)
            
            # Salva o frame
            cv2.imwrite(output_path, frame)
            saved_count += 1
            # logging.info(f"Salvo: {filename}")

        frame_count += 1

    cap.release()
    logging.info(f"Done! {saved_count} frames extracted.")


def detect_face(image_path):
    try:
        face_objs = DeepFace.extract_faces(img_path=image_path, detector_backend='opencv')
        return True, face_objs[0]['confidence']
    except ValueError:
        return False, 0

def calculate_required_density(gap_size):
    if gap_size <= 3:
        return 0.30
    elif gap_size <= 5:
        return 0.35 + (gap_size - 4) * 0.05
    else:
        return min(0.30 + gap_size * 0.025, 1.0)  # Aumenta 2.5% por elemento a partir de 5

def split_tuples(tuples_list, max_size=21):
    result = []
    
    for start, end in tuples_list:
        diff = end - start + 1  # +1 porque inclui ambos os extremos
        
        if diff <= max_size:
            result.append((start, end))
        else:
            current_start = start
            while current_start <= end:
                current_end = min(current_start + max_size - 1, end)
                result.append((current_start, current_end))
                current_start = current_end + 1
    
    return result

def adjust_tuples(tuples_list, min_limit=0, max_limit=18):
    adjusted = []
    
    for start, end in tuples_list:
        diff = end - start
        
        if diff <= 4:
            # Caso especial: tupla no limite mínimo
            if start == min_limit:
                new_start = start
                new_end = min(end + 2, max_limit)
            # Caso especial: tupla no limite máximo
            elif end >= max_limit:
                new_start = max(start - 2, min_limit)
                new_end = end
            # Caso normal: expande para ambos os lados
            else:
                new_start = max(start - 1, min_limit)
                new_end = min(end + 1, max_limit)
            
            adjusted.append((new_start, new_end))
        else:
            adjusted.append((start, end))
    
    return adjusted

def find_sequences(frames_folder, min_length=4, max_length=21):

    frames = sorted(os.listdir(frames_folder))
    len_frames = len(frames)
    confidence_scores = []
    detections = []
    
    # 1. Coletar todas as confianças e detecções
    for img in frames:
        image_path = os.path.join(frames_folder, img)
        detected, confidence = detect_face(image_path)
        if detected:
            logging.info(f"✅ Face Detected: {confidence:.2%} {image_path}")
        else:
            logging.info(f"❌ Not detected: {confidence:.2%} {image_path}")
        confidence_scores.append(confidence if detected else 0)
        detections.append(detected)
    # 1. Identificar todas as sequências de 1's com comprimento mínimo
    sequences = []
    n = len(detections)
    i = 0
    
    while i < n:
        if detections[i] == 1:
            start = i
            while i < n and detections[i] == 1:
                i += 1
            end = i - 1
            if (end - start + 1) >= 4:
                sequences.append((start, end))
        else:
            i += 1
    
    if not sequences:
        return []
    
    # 2. Função para agrupar com densidade relativa
    def group_sequences(seqs):
        grouped = [seqs[0]]
        for current in seqs[1:]:
            last_start, last_end = grouped[-1]
            current_start, current_end = current
            
            gap_start = last_end + 1
            gap_end = current_start - 1
            gap_size = gap_end - gap_start + 1
            
            if gap_size > 0:
                gap_ones = detections[gap_start:gap_end+1].count(1)
                density = gap_ones / gap_size
                required_density = calculate_required_density(gap_size)
            else:
                density = 1.0
            
            if (gap_size <= 0 
                or density >= required_density 
                or detections[gap_start:gap_end+1] in [[0],[0,1,0],[0,1,1,0],[0,1,0,1,0],[0,1,1,1,0]]
                ):
                grouped[-1] = (last_start, current_end)
            else:
                grouped.append(current)
        
        grouped = split_tuples(grouped)
        grouped = adjust_tuples(grouped, max_limit=len_frames)


        return grouped
    
    # 3. Agrupar iterativamente até não haver mais mudanças
    changed = True
    current_sequences = sequences.copy()
    
    while changed:
        new_sequences = group_sequences(current_sequences)
        changed = len(new_sequences) != len(current_sequences)
        current_sequences = new_sequences
    
    return current_sequences


def seconds_to_timestamp(seconds):
    return str(timedelta(seconds=seconds)).split('.')[0].zfill(8)

def has_consecutive_detections(detections, start, end, min_consecutive=4):
    consecutive = 0
    for i in range(start, end + 1):
        if detections[i]:
            consecutive += 1
            if consecutive >= min_consecutive:
                return True
        else:
            consecutive = 0
    return False

def video_cut(input, output, start_seconds, end_seconds):
    try:
        video = VideoFileClip(input)
        
        if start_seconds < 0 or end_seconds > video.duration:
            return f"Error: Times must be between 0 and {video.duration:.2f} seconds."
        if start_seconds >= end_seconds:
            return "Error: Start time must be less than end time."
        
        trecho = video.subclip(start_seconds, end_seconds)
        
        out_folder = '/'.join(output.split('/')[:-1])
        os.makedirs(out_folder, exist_ok=True)
        trecho.write_videofile(output, codec="libx264", audio_codec="aac")
        return "Video cut successfully!"
    
    except Exception as e:
        return f"Error: {str(e)}"

def check_ffmpeg_installed():
    ffmpeg_path = shutil.which('ffmpeg')
    ffprobe_path = shutil.which('ffprobe')
    
    if not ffmpeg_path or not ffprobe_path:
        raise EnvironmentError(
            "FFmpeg not found. Please install it:\n"
            "Linux: sudo apt install ffmpeg\n"
            "macOS: brew install ffmpeg\n"
            "Windows: choco install ffmpeg"
        )
    return ffmpeg_path, ffprobe_path

def resize_video(input_path, output_path, width=1280, height=720):
    """Resize video to 1280x720 by cropping ONLY the top for vertical videos"""
    out_folder = '/'.join(output_path.split('/')[:-1])
    os.makedirs(out_folder, exist_ok=True)
    try:
        ffmpeg_path, ffprobe_path = check_ffmpeg_installed()
        
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"File not found: {input_path}")

        # Obtém dimensões originais
        cmd_probe = [
            ffprobe_path,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            input_path
        ]
        
        original_dims = subprocess.check_output(cmd_probe).decode('utf-8').strip().split(',')
        original_width, original_height = map(int, original_dims)
        
        is_vertical = original_height > original_width

        if is_vertical:
            # Cálculo para cortar o TOPO
            scale_height = int(width * original_height / original_width)
            vf = [
                f"scale={width}:{scale_height}",  # Escala primeiro
                f"crop={width}:{height}:0:0",    # Corta o TOPO (y=0)
                f"pad={width}:{height}:0:0"      # Garante dimensão exata
            ]
        else:
            # Lógica para vídeos horizontais
            vf = [
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            ]

        cmd = [
            ffmpeg_path,
            '-i', input_path,
            '-vf', ",".join(vf),
            '-c:a', 'copy',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]
        
        # logging.info("Command executed:", " ".join(cmd))
        subprocess.run(cmd, check=True)
        # logging.info(f"✅ Processed video: {output_path}")
        # logging.info(f"Dimensions: Original {original_width}x{original_height} → Output {width}x{height}")
        return True

    except Exception as e:
        logging.error(f"❌ Error: {str(e)}")
        return False

def list_metadata(csv_file=CSV_FILE):
    rows = []
    if os.path.isfile(csv_file):
        with open(csv_file, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                video_metadata = {
                    'id': row.get('id'),
                    'url': row.get('url'),
                    'title': row.get('title'),
                    'playlist': row.get('playlist'),
                    'length': row.get('length'),
                    'downloaded': row.get('downloaded')
                }
                rows.append(video_metadata)

    return rows
s3 = boto3.client(
    's3',
    aws_access_key_id=config('S3_ACCESS_KEY'),
    aws_secret_access_key=config('S3_SECRET_KEY'),
    region_name=config('S3_REGION')  # Ex: 'us-east-1'
)

def upload_file_to_s3(bucket_name, local_path, s3_path):
    try:
        s3.upload_file(
            local_path,
            bucket_name,
            s3_path,
            ExtraArgs={
                'ACL': 'bucket-owner-full-control',  # Importante para acesso do cliente
                'Metadata': {
                    'uploaded-by': 'fiverr'
                }
            }
        )
        logging.info(f"File {local_path} send to {s3_path}")
        return True
    except Exception as e:
        logging.info(f"Error upload: {str(e)}")
        return False

## TO S3
jump = False # change to True to continue from last uploaded
for video_data in list_metadata():
    folder_id = video_data['id']
    youtube_id = video_data['url'].split('=')[-1]
    video_title = video_data['title']
    local_filename = f'{video_title} ({youtube_id}).mp4'
    videos_folder = DOWNLOADS_PATH
    s3_folder = video_data['id']
    if jump:
        cont = '2/Pregnant Mackenzie Huge Twin Belly Compilation | TV (IR4hyRyk_VI)'
        if f'{folder_id}/{video_title} ({youtube_id})' == cont:
            jump = False 
            logging.info(f'Continue after: {cont}')
        continue
    logging.info(f'Processing: {folder_id}/{video_title} {youtube_id}')

    # Extract frames
    frames_folder = f'frames/frames_{folder_id}'
    try:
        extract_frames_with_timestamps(f'{videos_folder}/{local_filename}', output_folder=frames_folder)
    except ValueError:
        try:
            local_filename = f'{video_title}.mp4'
            extract_frames_with_timestamps(f'{videos_folder}/{local_filename}', output_folder=frames_folder)
        except ValueError:
            try:
                local_filename = f'{video_title.replace('/','')}.mp4'
                extract_frames_with_timestamps(f'{videos_folder}/{local_filename}', output_folder=frames_folder)
            except ValueError:
                logging.error(f"Error opening video: {f'{folder_id} {videos_folder}/{local_filename}'}")
                continue

    # Find start-end index of faces
    subvideos_indexes = find_sequences(frames_folder, min_length=4)
    if not subvideos_indexes:
        logging.info(f"No relevant faces found: {folder_id} {videos_folder}/{local_filename}")
        continue
    logging.info(f"Video parts with faces: {len(subvideos_indexes)}. Seconds: {subvideos_indexes}")


    # Cut video parts, resize and upload
    for i, (start_seconds, end_seconds) in enumerate(subvideos_indexes):
        # Cut
        part_id = i+1
        start_time = seconds_to_timestamp(start_seconds)
        end_time = seconds_to_timestamp(end_seconds)
        logging.info(f"Video slice {part_id}: {start_seconds:.2f}s to {end_seconds:.2f}s ({start_time} to {end_time})")
        cut_filename = f'{video_title.replace('/', '-')} ({youtube_id}) {part_id}.mp4'
        cut_output = f's3_folder_out/{folder_id}/{cut_filename}'
        video_cut(f'{videos_folder}/{local_filename}', cut_output, start_seconds, end_seconds)
        # Resize
        resize_input = cut_output
        resize_output = cut_output.replace('_out/', '_out_1280x720/')
        resize_video(resize_input, resize_output, width=1280, height=720)
        # Upload
        upload_input = resize_output
        s3_filename = f'{cut_filename}'
        upload_output = f'{folder_id}/{s3_filename}'
        upload_file_to_s3(S3_BUCKET_PARTS, upload_input, upload_output)
        logging.info(f'Upload from {upload_input} to {S3_BUCKET_PARTS} {upload_output}')


## LOCAL

# for n in range(2,5):
#     videos_folder = f'download'
#     video_filenames = sorted(os.listdir(videos_folder))
#     for video_filename in video_filenames:
#         youtube_id = video_filename.split('(')[-1].split(')')[0]
#         print(n, youtube_id, video_filename)
#         frames_folder = f'frames/frames_{n}'
#         try:
#             extract_frames_with_timestamps(f'{videos_folder}/{video_filename}', output_folder=frames_folder)
#         except ValueError:
#             print(f"Error opening video: {f'{videos_folder}/{video_filename}'}")
#             continue
#         try:
#             # start_seconds, end_seconds, soma_conf = find_best_20s_segment(frames_folder, fps=1)
#             subvideos_indexes = find_sequences(frames_folder, min_length=4)
#         except TypeError:
#             print(f"No relevant faces found: {videos_folder}/{video_filename}")
#             continue
#         for i, (start_seconds, end_seconds) in enumerate(subvideos_indexes):
#             start_time = seconds_to_timestamp(start_seconds)
#             end_time = seconds_to_timestamp(end_seconds)
#             print(f"Video slice {n}: {start_seconds:.2f}s to {end_seconds:.2f}s ({start_time} to {end_time})")
#             output = f's3_folder_out/{n}/{'.'.join(video_filename.split('.')[:-1])}_{i+1}.mp4'
#             video_cut(f'{videos_folder}/{video_filename}', output, start_seconds, end_seconds)
#             resize_video(output, output.replace('_out/', '_out_1280x720/'), width=1280, height=720)

            

