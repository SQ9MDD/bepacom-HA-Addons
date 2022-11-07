from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from flask import Flask, jsonify, escape, request, render_template


#===================================================
# Flask setup (WebUI)
#===================================================
flask_app = Flask("WebUI", template_folder='templates')

@flask_app.route("/")
def flask_main():
    return render_template("index.html")


#===================================================
# FastAPI setup
#===================================================
app = FastAPI()

@app.get("/api")
async def root():
    return {"message": "Hello World"}

@app.get("/api/nice")
async def nicepage():
    return {"love": "u"}

# mounting flask into FastAPI
app.mount("/webapp", WSGIMiddleware(flask_app))


#app.add_middleware(
#    CORSMiddleware,
#    allow_origins=["*"],
#    allow_credentials=False,
#    allow_methods=["*"],
#    allow_headers=["*"],
#)