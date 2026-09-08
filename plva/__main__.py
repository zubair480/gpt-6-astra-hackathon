import uvicorn

if __name__ == '__main__':
    uvicorn.run('plva.server:app', host='127.0.0.1', port=18080)
