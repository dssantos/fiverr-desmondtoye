
import os
from datetime import timedelta
import shutil

import cv2
import mediapipe as mp
from deepface import DeepFace
from moviepy.editor import VideoFileClip


def extract_frames_with_timestamps(video_path, output_folder="frames", interval_sec=1):
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    os.makedirs(output_folder, exist_ok=True)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Erro ao abrir o vídeo: {f'{output_folder}/{video_path}'}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    print(f"Extraindo frames a cada {interval_sec} segundos...")
    print(f"Resumo: {fps:.2f} FPS | {total_frames} frames | {duration_sec:.2f} segundos")

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
            filename = f"frame_{timestamp.replace(':', '-')}.jpg"
            output_path = os.path.join(output_folder, filename)
            
            # Salva o frame
            cv2.imwrite(output_path, frame)
            saved_count += 1
            # print(f"Salvo: {filename}")

        frame_count += 1

    cap.release()
    print(f"Concluído! {saved_count} frames extraídos.")


def detect_face(image_path):
    try:
        face_objs = DeepFace.extract_faces(img_path=image_path, detector_backend='opencv')
        return True, face_objs[0]['confidence']
    except ValueError:
        return False, 0

def find_best_20s_segment(frames_folder, fps=1):
    frames = sorted(os.listdir(frames_folder))
    frame_count = len(frames)
    window_size = 21 * fps  # Número de frames em 20 segundos
    confidence_scores = []
    detections = []
    
    # 1. Coletar todas as confianças e detecções
    for img in frames:
        image_path = os.path.join(frames_folder, img)
        detected, confidence = detect_face(image_path)
        if detected:
            print(f"✅ Face Detected: {confidence:.2%} {image_path}")
        else:
            print(f"❌ Not detected: {confidence:.2%} {image_path}")
        confidence_scores.append(confidence if detected else 0)
        detections.append(detected)
    
    # 2. Encontrar todas as janelas válidas (com pelo menos 3 detecções consecutivas)
    valid_windows = []
    for i in range(frame_count - window_size + 1):
        start_frame = i
        end_frame = i + window_size - 1
        
        if has_consecutive_detections(detections, start_frame, end_frame):
            window_sum = sum(confidence_scores[start_frame:end_frame+1])
            valid_windows.append((start_frame, end_frame, window_sum))
    
    if not valid_windows:
        print("Nenhuma janela válida encontrada com 3+ detecções consecutivas")
        return None
    
    # 3. Selecionar a janela com maior soma de confiança
    valid_windows.sort(key=lambda x: x[2], reverse=True)
    best_window = valid_windows[0]
    
    # 4. Best window
    start_sec = best_window[0] / fps
    end_sec = best_window[1] / fps
    
    return (start_sec, end_sec, best_window[2])

def calculate_required_density(gap_size):
    """Calcula a densidade mínima requerida baseada no tamanho do intervalo"""
    if gap_size <= 3:
        return 0.30
    elif gap_size <= 5:
        return 0.35 + (gap_size - 4) * 0.05
    else:
        return min(0.30 + gap_size * 0.025, 1.0)  # Aumenta 2.5% por elemento a partir de 5

def find_sequences(frames_folder, min_length=3):

    frames = sorted(os.listdir(frames_folder))
    confidence_scores = []
    detections = []
    
    # 1. Coletar todas as confianças e detecções
    for img in frames:
        image_path = os.path.join(frames_folder, img)
        detected, confidence = detect_face(image_path)
        if detected:
            print(f"✅ Face Detected: {confidence:.2%} {image_path}")
        else:
            print(f"❌ Not detected: {confidence:.2%} {image_path}")
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
            if (end - start + 1) >= min_length:
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
            
            if gap_size <= 0 or density >= required_density:
                grouped[-1] = (last_start, current_end)
            else:
                grouped.append(current)
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
    """Converte segundos para formato 00:00:00"""
    return str(timedelta(seconds=seconds)).split('.')[0].zfill(8)

def has_consecutive_detections(detections, start, end, min_consecutive=4):
    """Verifica se há pelo menos 'min_consecutive' detecções consecutivas na janela"""
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
            return f"Erro: Os tempos devem estar entre 0 e {video.duration:.2f} segundos."
        if start_seconds >= end_seconds:
            return "Erro: O tempo inicial deve ser menor que o final."
        
        trecho = video.subclip(start_seconds, end_seconds)
        
        out_folder = '/'.join(output.split('/')[:-1])
        os.makedirs(out_folder, exist_ok=True)
        trecho.write_videofile(output, codec="libx264", audio_codec="aac")
        return "Vídeo cortado com sucesso!"
    
    except Exception as e:
        return f"Erro: {str(e)}"

for n in range(2,5):
    videos_folder = f's3_folder/{n}'
    video_filenames = sorted(os.listdir(videos_folder))
    for video_filename in video_filenames:
        youtube_id = video_filename.split('(')[-1].split(')')[0]
        print(n, youtube_id, video_filename)
        frames_folder = f'frames/frames_{n}'
        try:
            extract_frames_with_timestamps(f'{videos_folder}/{video_filename}', output_folder=frames_folder)
        except ValueError:
            print(f"Erro ao abrir o vídeo: {f'{videos_folder}/{video_filename}'}")
            continue
        try:
            # start_seconds, end_seconds, soma_conf = find_best_20s_segment(frames_folder, fps=1)
            subvideos_indexes = find_sequences(frames_folder, min_length=3)
        except TypeError:
            print(f"No relevant faces found: {videos_folder}/{video_filename}")
            continue
        for i, (start_seconds, end_seconds) in enumerate(subvideos_indexes):
            start_time = seconds_to_timestamp(start_seconds)
            end_time = seconds_to_timestamp(end_seconds)
            print(f"Trecho {n}: {start_seconds:.2f}s a {end_seconds:.2f}s ({start_time} a {end_time})")
            output = f's3_folder_out/{n}/{'.'.join(video_filename.split('.')[:-1])}_{i+1}.mp4'
            video_cut(f'{videos_folder}/{video_filename}', output, start_seconds, end_seconds)

            

