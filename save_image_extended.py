import os
import sys
import json
import time
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import numpy as np
#remove logging when done
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), 'comfy'))

import folder_paths

# remove when done
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class SaveImageExtended:
	def __init__(self):
		self.output_dir = folder_paths.get_output_directory()
		self.type = 'output'
		self.prefix_append = ''

	@classmethod
	def INPUT_TYPES(s):
		return {
			'required': {
				'images': ('IMAGE', ),
				'save_metadata': (['disabled', 'enabled'], {'default': 'enabled'}),
				'counter_digits': ([2, 3, 4, 5, 6], {'default': 3}),
				'filename_prefix': ('STRING', {'default': 'Yo'}),
				'filename_keys': ('STRING', {'default': 'steps, cfg', 'multiline': False}),
				'foldername_prefix': ('STRING', {'default': 'Hej'}),
				'foldername_keys': ('STRING', {'default': 'sampler_name, scheduler', 'multiline': False}),
				'prompt_to_file': (['disabled', 'enabled'],),
			},
			'hidden': {'prompt': 'PROMPT', 'extra_pnginfo': 'EXTRA_PNGINFO'},
		}

	RETURN_TYPES = ()
	FUNCTION = 'save_images'
	OUTPUT_NODE = True
	CATEGORY = 'image'

	def get_subfolder_path(self, image_path, output_path):
		output_parts = output_path.strip(os.sep).split(os.sep)
		image_parts = image_path.strip(os.sep).split(os.sep)
		common_parts = os.path.commonprefix([output_parts, image_parts])
		subfolder_parts = image_parts[len(common_parts):]
		subfolder_path = os.sep.join(subfolder_parts[:-1])
		return subfolder_path

	## Extract counter number from file names
	def get_latest_counter(self, folder_path, filename_prefix):
		counter = 1
		if not os.path.exists(folder_path):
			print(f"Folder {folder_path} does not exist, starting counter at 1.")
			return counter

		try:
			files = [f for f in os.listdir(folder_path) if f.startswith(filename_prefix) and f.endswith('.png')]
			if files:
				counters = [int(f[len(filename_prefix):-4]) for f in files]
				counter = max(counters) + 1
		except Exception as e:
			print(f"An error occurred while finding the latest counter: {e}")
		return counter

	@staticmethod
	def find_k_sampler_class_type(prompt):
		for key, value in prompt.items():
			if 'class_type' in value:
				class_type = value.get('class_type')
				if 'Eff. Loader SDXL' in class_type:
					print(f'Found Eff. Loader SDXL class_type in key: {key}, class_type: {class_type}')
					return key, class_type
		return None

	@staticmethod
	def find_keys_recursively(d, keys_to_find, found_values):
		for key, value in d.items():
			if key in keys_to_find:
				found_values[key] = value
			if isinstance(value, dict):
				SaveImageExtended.find_keys_recursively(value, keys_to_find, found_values)

	def save_images(self, images, filename_prefix, filename_keys, foldername_prefix, foldername_keys, prompt_to_file, counter_digits, save_metadata, prompt=None, extra_pnginfo=None):

		## Generate file name
		filename_keys_to_extract = [item.strip() for item in filename_keys.split(',')]
		custom_filename = ''
		if len(filename_prefix) > 0:
			custom_filename = f'{filename_prefix}_'

		if prompt is not None and len(filename_keys_to_extract) > 0:
			found_values = {}
			self.find_keys_recursively(prompt, filename_keys_to_extract, found_values)
			for key in filename_keys_to_extract:
				value = found_values.get(key)
				if value is not None:
					custom_filename += f'{value}_'

		## Generate folder name
		foldername_keys_to_extract = [item.strip() for item in foldername_keys.split(',')]
		custom_foldername = foldername_prefix

		if prompt is not None and len(foldername_keys_to_extract) > 0:
			found_values = {}
			self.find_keys_recursively(prompt, foldername_keys_to_extract, found_values)
			for key in foldername_keys_to_extract:
				value = found_values.get(key)
				if value is not None:
					custom_foldername += f'_{value}'

		## Create and save images
		try:
			full_output_folder, filename, _, _, custom_filename = folder_paths.get_save_image_path(custom_filename, self.output_dir, images[0].shape[1], images[0].shape[0])
			output_path = os.path.join(full_output_folder, custom_foldername)
			os.makedirs(output_path, exist_ok=True)
			counter = self.get_latest_counter(output_path, filename)

			results = list()
			for image in images:
				i = 255. * image.cpu().numpy()
				img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
				metadata = None
				if save_metadata == 'enabled':
					metadata = PngInfo()
					if prompt is not None:
						metadata.add_text('prompt', json.dumps(prompt))
					if extra_pnginfo is not None:
						for x in extra_pnginfo:
							metadata.add_text(x, json.dumps(extra_pnginfo[x]))

				file = f'{filename}{counter:0{counter_digits}}.png'
				image_path = os.path.join(output_path, file)
				img.save(image_path, pnginfo=metadata, compress_level=4)
				counter += 1

				subfolder = self.get_subfolder_path(image_path, self.output_dir)
				results.append({ 'filename': file, 'subfolder': subfolder, 'type': self.type})

				#remove when done
				# logging.info(f"Prompt: {json.dumps(prompt, indent=4)}")

			## If enabled, save positive & negative prompt to JSON
			if prompt_to_file =='enabled':
				if prompt is not None:
					prompt_keys_to_save = {}

					for key in prompt:
						class_type = prompt[key].get('class_type', None)
						inputs = prompt[key].get('inputs', {})

						# Efficiency Loader prompt structure
						if class_type == 'Eff. Loader SDXL':
							if 'positive' in inputs and 'negative' in inputs:
								prompt_keys_to_save['positive'] = inputs.get('positive')
								prompt_keys_to_save['negative'] = inputs.get('negative')

						# Original KSampler prompt structure
						elif class_type == 'KSampler' or class_type == 'UltimateSDUpscale':
							positive_ref = inputs.get('positive', [])[0] if 'positive' in inputs else None
							negative_ref = inputs.get('negative', [])[0] if 'negative' in inputs else None

							positive_text = prompt.get(str(positive_ref), {}).get('inputs', {}).get('text', None)
							negative_text = prompt.get(str(negative_ref), {}).get('inputs', {}).get('text', None)

							if positive_text:
								prompt_keys_to_save['positive_text'] = positive_text

							if negative_text:
								prompt_keys_to_save['negative_text'] = negative_text

				# Append data to JSON file
				json_file_path = os.path.join(output_path, 'prompts.json')
				existing_data = {}

				if os.path.exists(json_file_path):
					with open(json_file_path, 'r') as f:
						existing_data = json.load(f)

				timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
				new_entry = {}
				new_entry[timestamp] = prompt_keys_to_save
				existing_data.update(new_entry)

				with open(json_file_path, 'w') as f:
					json.dump(existing_data, f, indent=4)

		except OSError as e:
			print(f'An error occurred while creating the subfolder or saving the image: {e}')
		else:
			return { 'ui': { 'images': results } }

NODE_CLASS_MAPPINGS = {
    'SaveImageExtended': SaveImageExtended,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    'SaveImageExtended': 'Save Image Extended',
}
