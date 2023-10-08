import os
import re
import sys
import json
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import numpy as np
import locale
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), 'comfy'))
original_locale = locale.setlocale(locale.LC_TIME, '')

import folder_paths

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
				'filename_prefix': ('STRING', {'default': 'myFile'}),
				'filename_keys': ('STRING', {'default': 'steps, cfg', 'multiline': False}),
				'foldername_prefix': ('STRING', {'default': 'myPix'}),
				'foldername_keys': ('STRING', {'default': 'sampler_name, scheduler', 'multiline': False}),
				'delimiter': (['underscore','dot', 'comma'], {'default': 'underscore'}),
				'save_job_data': (['disabled', 'prompt', 'basic, prompt', 'basic, sampler, prompt', 'basic, models, sampler, prompt'],{'default': 'basic, prompt'}),
				'save_metadata': (['disabled', 'enabled'], {'default': 'enabled'}),
				'counter_digits': ([2, 3, 4, 5, 6], {'default': 3}),
				'counter_position': (['first', 'last'], {'default': 'last'}),
				'image_preview': (['disabled', 'enabled'], {'default': 'enabled'}),
			},
			"optional": {
                    "positive_text_opt": ("STRING", {"forceInput": True}),
					"negative_text_opt": ("STRING", {"forceInput": True}),
                    },
			'hidden': {'prompt': 'PROMPT', 'extra_pnginfo': 'EXTRA_PNGINFO'},
		}

	RETURN_TYPES = ()
	FUNCTION = 'save_images'
	OUTPUT_NODE = True
	CATEGORY = 'image'

	def get_subfolder_path(self, image_path, output_path):
		image_path = Path(image_path).resolve()
		output_path = Path(output_path).resolve()
		relative_path = image_path.relative_to(output_path)
		subfolder_path = relative_path.parent

		return str(subfolder_path)

	# Get current counter number from file names
	def get_latest_counter(self, folder_path, filename_prefix, counter_digits, counter_position='last'):
		counter = 1
		if not os.path.exists(folder_path):
			print(f"Folder {folder_path} does not exist, starting counter at 1.")
			return counter

		try:
			files = [f for f in os.listdir(folder_path) if f.endswith('.png')]
			if files:
				if counter_position == 'last':
					counters = [int(f[-(4 + counter_digits):-4]) for f in files if f.startswith(filename_prefix)]
				elif counter_position == 'first':
					counters = [int(f[:counter_digits]) for f in files if f[counter_digits:].startswith(filename_prefix)]
				else:
					print("Invalid counter_position. Using 'last' as default.")
					counters = [int(f[-(4 + counter_digits):-4]) for f in files if f.startswith(filename_prefix)]

				if counters:
					counter = max(counters) + 1

		except Exception as e:
			print(f"An error occurred while finding the latest counter: {e}")

		return counter

	@staticmethod
	def find_keys_recursively(d, keys_to_find, found_values):
		for key, value in d.items():
			if key in keys_to_find:
				found_values[key] = value
			if isinstance(value, dict):
				SaveImageExtended.find_keys_recursively(value, keys_to_find, found_values)

	@staticmethod
	def find_parameter_values(target_keys, obj, found_values=None):
		if found_values is None:
			found_values = {}

		if not isinstance(target_keys, list):
			target_keys = [target_keys]

		loras_string = ''
		for key, value in obj.items():
			if 'loras' in target_keys:
				# Match both formats: lora_xx and lora_name_x
				if re.match(r'lora(_name)?_\d+', key):
					if value.endswith('.safetensors'):
						value = value.replace('.safetensors', '', 1)
					if value != 'None':
						loras_string += f'{value}, '

			if key in target_keys:
				if isinstance(value, str) and value.endswith('.safetensors'):
					base_value = os.path.basename(value)
					value = base_value[:-12]
				found_values[key] = value

			# Recursively search in nested dictionaries
			if isinstance(value, dict):
				SaveImageExtended.find_parameter_values(target_keys, value, found_values)

		if 'loras' in target_keys and loras_string:
			found_values['loras'] = loras_string.strip(', ')

		if len(target_keys) == 1:
			return found_values.get(target_keys[0], None)

		return found_values

	@staticmethod
	def generate_custom_name(keys_to_extract, prefix, delimiter_char, resolution, prompt):
		custom_name = prefix

		if prompt is not None and len(keys_to_extract) > 0:
			found_values = {'resolution': resolution}
			SaveImageExtended.find_keys_recursively(prompt, keys_to_extract, found_values)
			for key in keys_to_extract:
				value = found_values.get(key)
				if value is not None:
					if isinstance(value, str) and value.endswith('.safetensors'):
						base_value = os.path.basename(value)
						value = base_value[:-12]

					custom_name += f'{delimiter_char}{value}'

		return custom_name.strip(delimiter_char)

	def save_images(self,
				 counter_digits,
				 counter_position,
				 delimiter,
				 filename_keys,
				 foldername_keys,
				 images,
				 image_preview,
				 save_job_data,
				 save_metadata,
				 filename_prefix='',
				 foldername_prefix='',
				 extra_pnginfo=None,
				 negative_text_opt=None,
				 positive_text_opt=None,
				 prompt=None
				):

		delimiter_char = "_" if delimiter =='underscore' else '.' if delimiter =='dot' else ','

		# Get set resolution value
		i = 255. * images[0].cpu().numpy()
		img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
		resolution = f'{img.width}x{img.height}'

		filename_keys_to_extract = [item.strip() for item in filename_keys.split(',')]
		foldername_keys_to_extract = [item.strip() for item in foldername_keys.split(',')]
		custom_filename = SaveImageExtended.generate_custom_name(filename_keys_to_extract, filename_prefix, delimiter_char, resolution, prompt)
		custom_foldername = SaveImageExtended.generate_custom_name(foldername_keys_to_extract, foldername_prefix, delimiter_char, resolution, prompt)

		# Create and save images
		try:
			full_output_folder, filename, _, _, custom_filename = folder_paths.get_save_image_path(custom_filename, self.output_dir, images[0].shape[1], images[0].shape[0])
			output_path = os.path.join(full_output_folder, custom_foldername)
			os.makedirs(output_path, exist_ok=True)
			counter = self.get_latest_counter(output_path, filename, counter_digits, counter_position)

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

				if counter_position == 'last':
					file = f'{filename}{delimiter_char}{counter:0{counter_digits}}.png'
				else:
					file = f'{counter:0{counter_digits}}{delimiter_char}{filename}.png'

				image_path = os.path.join(output_path, file)
				img.save(image_path, pnginfo=metadata, compress_level=4)
				counter += 1

				subfolder = self.get_subfolder_path(image_path, self.output_dir)
				results.append({ 'filename': file, 'subfolder': subfolder, 'type': self.type})

			# Save job data to json
			if save_job_data != 'disabled':

				prompt_keys_to_save = {}
				if 'basic' in save_job_data:
					if len(filename_prefix) > 0:
						prompt_keys_to_save['filename_prefix'] = filename_prefix
					prompt_keys_to_save['resolution'] = resolution

				if 'models' in save_job_data:
					models = SaveImageExtended.find_parameter_values(['ckpt_name', 'loras', 'vae_name'], prompt)
					if models['ckpt_name']:
						prompt_keys_to_save['checkpoint'] = models['ckpt_name']
					if models['loras']:
						prompt_keys_to_save['loras'] = models['loras']
					if models['vae_name']:
						prompt_keys_to_save['vae'] = models['vae_name']

				if 'sampler' in save_job_data:
					prompt_keys_to_save['sampler_parameters'] = SaveImageExtended.find_parameter_values(['seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise'], prompt)

				if 'prompt' in save_job_data:
					if positive_text_opt is not None:
						if not (isinstance(positive_text_opt, list) and
								len(positive_text_opt) == 2 and
								isinstance(positive_text_opt[0], str) and
								len(positive_text_opt[0]) < 6 and
								isinstance(positive_text_opt[1], (int, float))):
							prompt_keys_to_save['positive_prompt'] = positive_text_opt

					if negative_text_opt is not None:
						if not (isinstance(positive_text_opt, list) and len(negative_text_opt) == 2 and isinstance(negative_text_opt[0], str) and isinstance(negative_text_opt[1], (int, float))):
							prompt_keys_to_save['negative_prompt'] = negative_text_opt

					#If no user input for prompts
					if positive_text_opt is None and negative_text_opt is None:
						if prompt is not None:
							for key in prompt:
								class_type = prompt[key].get('class_type', None)
								inputs = prompt[key].get('inputs', {})

								# Efficiency Loaders prompt structure
								if class_type == 'Efficient Loader' or class_type == 'Eff. Loader SDXL':
									if 'positive' in inputs and 'negative' in inputs:
										prompt_keys_to_save['positive_prompt'] = inputs.get('positive')
										prompt_keys_to_save['negative_prompt'] = inputs.get('negative')

								# KSampler/UltimateSDUpscale prompt structure
								elif class_type == 'KSampler' or class_type == 'KSamplerAdvanced' or class_type == 'UltimateSDUpscale':
									positive_ref = inputs.get('positive', [])[0] if 'positive' in inputs else None
									negative_ref = inputs.get('negative', [])[0] if 'negative' in inputs else None

									positive_text = prompt.get(str(positive_ref), {}).get('inputs', {}).get('text', None)
									negative_text = prompt.get(str(negative_ref), {}).get('inputs', {}).get('text', None)

									# If we get non text inputs
									if positive_text is not None:
										if isinstance(positive_text, list):
											if len(positive_text) == 2:
												if isinstance(positive_text[0], str) and len(positive_text[0]) < 6:
													if isinstance(positive_text[1], (int, float)):
														continue
										prompt_keys_to_save['positive_prompt'] = positive_text

									if negative_text is not None:
										if isinstance(negative_text, list):
											if len(negative_text) == 2:
												if isinstance(negative_text[0], str) and len(negative_text[0]) < 6:
													if isinstance(negative_text[1], (int, float)):
														continue
										prompt_keys_to_save['positive_prompt'] = negative_text

				# Append data and save
				json_file_path = os.path.join(output_path, 'jobs.json')
				existing_data = {}

				if os.path.exists(json_file_path):
					try:
						with open(json_file_path, 'r') as f:
							existing_data = json.load(f)
					except json.JSONDecodeError:
						print(f"The file {json_file_path} is empty or malformed. Initializing with empty data.")
						existing_data = {}

				timestamp = datetime.now().strftime('%c')
				new_entry = {}
				new_entry[timestamp] = prompt_keys_to_save
				existing_data.update(new_entry)

				with open(json_file_path, 'w') as f:
					json.dump(existing_data, f, indent=4)


		except OSError as e:
			print(f'An error occurred while creating the subfolder or saving the image: {e}')
		else:
			if image_preview == 'disabled':
				results = list()
			return { 'ui': { 'images': results } }

NODE_CLASS_MAPPINGS = {
    'SaveImageExtended': SaveImageExtended,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    'SaveImageExtended': 'Save Image Extended',
}
