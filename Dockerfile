# Imagen del servidor de la yincana. El backend es stdlib puro, así que no hay
# pip install: la imagen es el intérprete y el código, nada más.
FROM python:3.12-slim

WORKDIR /app
COPY . .

# El estado (yincana.db + cache_teselas/) vive en el volumen: el contenedor es
# desechable y la partida sobrevive a las reconstrucciones.
ENV YINCANA_DATOS=/datos

EXPOSE 8000
CMD ["python", "servidor.py", "--puerto", "8000"]
