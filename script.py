import os
import csv
from time import sleep
from datetime import datetime
import logging

from openpyxl import load_workbook
from pytubefix import YouTube, Playlist
from pytubefix.cli import on_progress

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

# Nome do arquivo CSV
CSV_FILE = 'links.csv'  # ajuste para o nome do seu arquivo

def update_csv(video_data):
    """Atualiza ou adiciona a linha do CSV com base em video_data['url']."""
    rows = []
    found = False

    # Lê o arquivo se existir
    if os.path.isfile(CSV_FILE):
        with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row.get('url') == video_data['url']:
                    rows.append(video_data)  # substitui linha existente
                    found = True
                else:
                    rows.append(row)

    # Se não achou, adiciona como novo
    if not found:
        rows.append(video_data)

    # Escreve tudo de volta (ou cria novo arquivo com cabeçalho)
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=video_data.keys())
        writer.writeheader()
        writer.writerows(rows)

def not_downloaded(csv_file):
    """Retorna uma lista de URLs do CSV que ainda não foram baixados."""
    downloaded_urls = set()
    all_urls = set()
    
    if not os.path.exists(csv_file):
        return []
    
    with open(csv_file, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            all_urls.add(row['url'])
            if row.get('downloaded', '').lower() == 'true':
                downloaded_urls.add(row['url'])
    
    return list(all_urls - downloaded_urls)

def extrair_links_com_ids(arquivo_xlsx):
    try:
        # Carrega o arquivo Excel
        wb = load_workbook(arquivo_xlsx)
        planilha = wb.active
        
        # Encontra a coluna 'LINK'
        coluna_link = None
        for cell in planilha[1]:  # Verifica a primeira linha (cabeçalho)
            if cell.value and str(cell.value).strip().upper() == 'LINK':
                coluna_link = cell.column_letter
                break
        
        if not coluna_link:
            raise ValueError("Coluna 'LINK' não encontrada na planilha")
        
        # Extrai os dados
        dados = []
        for idx, row in enumerate(planilha.iter_rows(min_row=2, values_only=True), start=2):
            link = row[ord(coluna_link.lower()) - ord('a')]  # Converte letra para índice
            if link:  # Ignora linhas vazias
                dados.append({'id': idx, 'link': str(link)})
        
        return dados
        
    except Exception as e:
        logging.error(f"Erro ao processar arquivo: {str(e)}")
        return []

# Uso:
# links = extrair_links_com_ids('planilha.xlsx')
# for item in links:
#     print(f"ID: {item['id']}, Link: {item['link']}")

def extract_urls_from_playlist(url):
    pl = Playlist(url)

    return pl.video_urls

def buscar_titulo_por_url(url_procurada):
    try:
        with open(CSV_FILE, mode='r', encoding='utf-8') as arquivo:
            leitor = csv.DictReader(arquivo)
            
            for linha in leitor:
                if linha.get('url') == url_procurada:
                    return linha.get('title'), linha.get('length')
            
            # logging.info(f"URL '{url_procurada}' não encontrada no arquivo.")
            return '', ''
            
    except FileNotFoundError:
        logging.error(f"Erro: Arquivo '{CSV_FILE}' não encontrado.")
        return '', ''
    except Exception as e:
        logging.error(f"Erro ao processar o CSV: {str(e)}")
        return '', ''

def download_from_youtube(input_url, download=True):
    input_url_id = input_url['id']
    input_url = input_url['link']
    if 'playlist?list' in input_url:
        urls = extract_urls_from_playlist(input_url)
        logging.info(f'Playlist Urls to download: {len(urls)} {input_url}')
        playlist = input_url
    else:
        urls = [input_url]
        playlist = None
    for url in urls:
        title, length = buscar_titulo_por_url(url)
        if title != None and title != '':
            result = {
                "url": url,
                "title": title,
                "playlist": playlist,
                "length": length,
                "downloaded": True
            }
            logging.info(f'Video exists: {url} {title}')
            continue
        yt = YouTube(url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        length = yt.length
        title = yt.title

        ys = yt.streams.get_highest_resolution()
        result = {
            "url": url,
            "title": title,
            "playlist": playlist,
            "length": length,
            "downloaded": False
        }
        logging.info(result)
        logging.info('\n')
        download_path = 'downloads'
        if download:
            ys.download(output_path=download_path)
            sleep(5)
            if os.path.isfile(f'{download_path}/{title}.mp4'):
                result['downloaded'] = True
        update_csv(result)
        sleep(5)
    if playlist and download:
        result = {
            "url": playlist,
            "title": None,
            "playlist": playlist,
            "length": None,
            "downloaded": True
        }
        update_csv(result)

urls_to_download = extrair_links_com_ids('Copy of Pregnant Face Dataset.xlsx') # not_downloaded('links.csv')
logging.info(f'Urls to download: {len(urls_to_download)}')
for new_url in urls_to_download:
    download_from_youtube(new_url)#, download=False)
logging.info('\nFinished!')