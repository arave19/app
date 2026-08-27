# -*- coding: utf-8 -*-
# Que el Espíritu Santo de Dios sea guiando este código para los buenos propósitos.

from flask import Flask, Response, request, jsonify
from flask_cors import CORS
from flask import render_template, url_for
import os


app = Flask(__name__)

@app.route("/", methods=['GET', 'POST'])
def raiz():
	response = {}
	response["code"] = 200
	response["description"] = "Use the endpoints to get your reserved information. For more information about this development contact with the admin"
    
	return response, 200

from operation.habi import habi_data_crawling_api
app.register_blueprint(habi_data_crawling_api, url_prefix='/habi/data_crawling')
