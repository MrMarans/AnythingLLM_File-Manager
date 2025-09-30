import os
import time
from datetime import datetime
import requests
from django.utils import timezone
from .models import FileInfo, TaskError, created_workspaces
from .describe_images import ImageDescriber
from pathlib import Path

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from .sort_files import SortFiles

class FileScanner:
    def __init__(self, verbose = False):
        self.verbose = verbose
        self.files_to_add = []
        self.files_that_changed = []
        self.files_got_deleted = []

        self.image_describer = ImageDescriber(verbose=self.verbose)

        self.host_folders = [
            str(f) for f in Path("/app").iterdir()
            if f.is_dir() and f.name.lower().startswith("anythingllm")
        ]

        self.image_description_activate = os.environ.get("IMAGE_DESCRIPTION_ACTIVATE", "false").lower() == "true"
        if not self.image_description_activate:
            self.image_description_activate = False

    def reset(self):
        self.files_to_add = []
        self.files_that_changed = []
        self.files_got_deleted = []
        
        self.image_description_activate = os.environ.get("IMAGE_DESCRIPTION_ACTIVATE", "false").lower() == "true"
        if not self.image_description_activate:
            self.image_description_activate = False

    def scan_files(self):
        if self.verbose: print(f"image_description_active: {self.image_description_activate}")
        self._check_for_files_still_exist()
        if self.verbose: print(f"checking subfolder")
        for host_folder in self.host_folders:
            self._check_subfolder( directory = host_folder, main_folder = host_folder, first_run = True)
        if self.verbose: print(f"removing duplicates")
        self._remove_duplicates()
        if self.verbose: 
            print(f"Files to add: {self.files_to_add}")
            print(f"Files that changed: {self.files_that_changed}")
            print(f"Files got deleted: {self.files_got_deleted}")
            print(
                f"Found {len(self.files_to_add)} files to add, {len(self.files_that_changed)} files that changed and {len(self.files_got_deleted)} files that got deleted. Updating AnythingLLM now"
            )
            if (
                len(self.files_got_deleted) == 0
                and len(self.files_to_add) == 0
                and len(self.files_that_changed) == 0
            ):
                print("Since no changes have been detected, nothing happens")
                TaskError.objects.create(success=True, error="Early stop cause no changes")
                print("Nothing to update")
        
        return self.files_to_add, self.files_that_changed, self.files_got_deleted

    def create_image_descriptions(self):
        if self.verbose: print(f"image_description_activate: {self.image_description_activate}")
        self.image_description_activate= True
        for host_folder in self.host_folders:
            self._check_subfolder( directory = host_folder, main_folder = host_folder, first_run = True)
        self._remove_duplicates()

    def _check_for_files_still_exist(self):
        # ----------------------------
        # We go through each file in the DB and check if the file is still there
        # ----------------------------
        try:
            all_files = FileInfo.objects.all()
            for file in all_files:
                if not os.path.exists(file.absolute_path):
                    # if file doesnt exist anymore
                    self.files_got_deleted.append(
                        [file.absolute_path, file.main_folder, file.filename]
                    )
                    file.delete()

        except Exception as e:
            print(
                f"Error when checking for files from DB if they still exist in directory: {str(e)}"
            )

    def _check_subfolder(self,directory, main_folder, first_run):
        try:
            # Konvertiere den Eingabepfad in ein Path-Objekt
            directory_path = Path(directory)
            # Liste alle Dateien im Verzeichnis
            for file_path in directory_path.iterdir():
                file_name = file_path.name
                image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp')

                if self.verbose: print(f"Checking file: {file_name} in directory: {directory}")
                if file_path.is_dir():
                    self._check_subfolder(str(file_path), file_name, False)
                    pass
                elif first_run:
                    break
                elif file_name.lower().endswith(image_extensions) and self.image_description_activate:
                    # Check if .image_description file exists
                    description_file = file_path.with_suffix('.image_description')
                    if description_file.exists():
                        continue
                    description_path, worked = self.image_describer.image_to_description(str(file_path))
                    if worked:
                        self._file_in_db_or_updated(file_name, str(description_path), main_folder)
                    else:
                        print(f"Error when creating image description for {file_name}: {description_path}")
                        continue
                else:
                    self._file_in_db_or_updated(file_name, str(file_path), main_folder)

        except Exception as e:
            print(f"Error parsing {directory}: {str(e)} ")

    def _file_in_db_or_updated(self, file_name, file_path, main_folder):
        file_info = self._is_File_In_DB(file_name, file_path)
        if file_info is None:  # Wenn die Datei NICHT in der DB ist
            self.files_to_add.append([file_path, main_folder.lower().replace(" ", "-"), file_name])
        else:  # Wenn die Datei in der DB ist
            if self._file_Changed(file_info, file_path):
                self.files_that_changed.append([file_path, main_folder.lower().replace(" ", "-"), file_name])
                if self.verbose: print(f"File {file_name} has changed.")

    def _is_File_In_DB(self,file_name, file_path):
        if self.verbose: print(f"Checking if file {file_name} in is in the DB")
        try:
            # Normalisiere den Pfad mit pathlib
            normalized_path = Path(file_path).resolve()
            file_info = FileInfo.objects.filter(
                filename=file_name, 
                absolute_path=str(normalized_path)
            ).first()
            
            if file_info is not None:  # Wenn ein Objekt gefunden wurde
                if self.verbose: print(f"File {file_name} is in the DB")
                return file_info  # Gib das FileInfo Objekt zurück
            else:  # Wenn kein Objekt gefunden wurde (None)
                if self.verbose: print(f"File {file_name} is not in the DB")
                return None
        except Exception as e:
            print(f"Error checking file in DB: {str(e)}")
            return None


    def _remove_duplicates(self):
        arrays_to_check = [self.files_to_add, self.files_got_deleted, self.files_that_changed]
        for array in arrays_to_check:
            seen_files = set()
            array = [
                    file_info for file_info in array
                    if tuple(file_info) not in seen_files and not seen_files.add(tuple(file_info))
                ]

    def _file_Changed(self, file_in_db, file_path):
        try:
            creation_time = os.path.getctime(file_path)
            modification_time = os.path.getmtime(file_path)

            found_file_size = os.path.getsize(file_path)
            found_created_at = timezone.make_aware(
                datetime.fromtimestamp(creation_time)
            )
            found_modified_at = timezone.make_aware(
                datetime.fromtimestamp(modification_time)
            )
            
            return (
                file_in_db.file_size != found_file_size
                or file_in_db.created_at < found_created_at
                or file_in_db.modified_at < found_modified_at
            )
        except Exception as e:
            print(f"Error checking if file changed: {str(e)}")
            return False


class AnythingLLM_API_Client:
    def __init__(self, api_version = "v1", verbose = False):
        
        self.verbose = verbose

        # Get AnythingLLM API key and URL from environment variables
        self.AnythingLLM_api = os.environ.get("ANYTHING_LLM_API")
        if not self.AnythingLLM_api:
            raise ValueError("ANYTHING_LLM_API environment variable is not set")

        self.main_url = os.environ.get("ANYTHING_LLM_URL")
        if not self.main_url:
            raise ValueError("ANYTHING_LLM_URL environment variable is not set")

        self.headers_json = {  #Header for most request types
            "accept": "application/json",
            "Authorization": f"Bearer {self.AnythingLLM_api}",
            "Content-Type": "application/json",
        }
        self.headers_files = {  #Header for file upload requests
                "accept": "application/json",
                "Authorization": f"Bearer {self.AnythingLLM_api}",
            }
        
        self.api_version = api_version
        self.update_embeddings = []
        self._configure_api_version()

    def reset(self):
        self.update_embeddings = []

    def _configure_api_version(self):
        if self.api_version == "v1":
            # different urls parts for the API
            self.get_workspaces_url = "/api/v1/workspaces"
            self.get_documents_url = "/api/v1/documents"
            self.delete_documents_url = "/api/v1/system/remove-documents"
            self.post_document_add_url = "/api/v1/document/upload/"
            self.create_folder_url = "/api/v1/document/create-folder"
            self.move_to_folder_url = "/api/v1/document/move-files"
            self.get_workspace_url = "/api/v1/workspace/"
            self.update_embeddings_url = "/update-embeddings"
            self.new_workspace_url = "/api/v1/workspace/new"
            self.delete_folder_url = "/api/v1/document/remove-folder"

    def update(self, files_to_add, files_that_changed, files_got_deleted ):
        try:
            self.add_files_to_anythingLLM(files_to_add)
            self.delete_files_from_anythingLLM(files_got_deleted)
            self.update_files_in_anythingLLM(files_that_changed)
            self.update_workspace_embeddings(self.update_embeddings)
            self.delete_unused_workspaces()
            self.delete_unused_folders()

            if self.verbose:
                print(f"Done Updating, task was successful. {len(FileInfo.objects.all())} documents in DB")

        
            TaskError.objects.create(success=True, error=None)
            print(f"Done Updating, task was successful. Found {len(files_to_add)} files to add, {len(files_that_changed)} files that changed and {len(files_got_deleted)} files that got deleted.")
        except Exception as e:
            print(f"Error in task execution: {e}")
            TaskError.objects.create(success=False, error=str(e))

    def add_files_to_anythingLLM(self, files_to_add):
        # -----------------------------
        # This function sends files to AnythingLLM via the api.
        # files_to_add has arrays of this structure: [file_path, main_folder, file_name]
        # We are going through each file and send them one by one to AnythingLLM
        # -----------------------------
        try:
            
            for file in files_to_add:
                file_path = file[0]
                folder_name = file[1]

                # Prüfe ob die Datei noch existiert
                if not os.path.exists(file_path):
                    if self.verbose: print(f"Skipping file {file_path} as it no longer exists")
                    continue

                # Open and prepare the file for upload
                with open(file_path, "rb") as f:
                    files = {
                        "file": (os.path.basename(file_path), f, "application/octet-stream")
                    }

                    if self.verbose: print(f"Uploading file {file_path} to AnythingLLM: {self.main_url + self.post_document_add_url}")

                    response = requests.post(
                        self.main_url + self.post_document_add_url + folder_name,
                        headers=self.headers_files,
                        files=files,
                        timeout=1200,  # Increased timeout for file uploads
                        verify=False
                    )
                    if response.status_code != 200:
                        if self.verbose: print(f"Error uploading file {file_path} to AnythingLLM: {response.json()}")
                        continue

                    doc_info = response.json()["documents"]
                    location = doc_info[0][
                        "location"
                    ]  # saving information of where it was saved within anythingLLM

                    if response.status_code == 200:
                        start = location.find("/") + 1
                        only_file_name = location[start:]
                        # Save the file info to our database if upload was successful
                        self._saveFile(file_path, folder_name)
                        self.update_embeddings.append([folder_name, only_file_name])
        except Exception as e:
            print(f"Error adding files to anythingLLM: {str(e)}")

    def delete_files_from_anythingLLM(self, array_to_delete):
        # -----------------------------
        # This function deletes files from AnythingLLM, because they either got changed or deleted.
        # array_to_delete has arrays of this structure: [file_path, main_folder, file_name]
        # We are going through each file and delete them one by one in AnythingLLM
        # -----------------------------

        # Convert array format for AnythingLLM comparison
        files_to_delete = [[file[2], file[1]] for file in array_to_delete]

        try:
            # Get all documents from AnythingLLM
            response = requests.get(
                self.main_url + self.get_documents_url, headers=self.headers_json, timeout=120, verify=False
            )
            response.raise_for_status()
            local_files = response.json()["localFiles"]
            folders = local_files["items"]

            # Build list of files to delete from AnythingLLM
            paths_to_delete = []
            for folder in folders:
                folder_name = folder["name"]
                for doc in folder["items"]:
                    if [doc["title"], folder_name] in files_to_delete:
                        doc_path = f"{folder_name}/{doc['name']}"
                        paths_to_delete.append(doc_path)

            # Delete from AnythingLLM if we found any files
            if paths_to_delete:
                response = requests.delete(
                    self.main_url + self.delete_documents_url,
                    headers=self.headers_json,
                    json={"names": paths_to_delete},
                    timeout=120,
                    verify=False
                )
                response.raise_for_status()

            # Delete from database
            for file in array_to_delete:
                FileInfo.objects.filter(filename=file[2], absolute_path=file[0]).delete()

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error communicating with AnythingLLM: {str(e)}")
        except Exception as e:
            raise Exception(f"Error in delete_files_from_anythingLLM: {str(e)}")

    def update_files_in_anythingLLM(self, files_that_changed):
        # -----------------------------
        # We are checking the files that got changed, deleting them from our DB and from AnythingLLM, then reuploading them.
        # files_that_changed has arrays of this structure: [file_path, main_folder, file_name]
        # -----------------------------

        try:
            # First, remove ALL existing entries for these files from DB
            for file in files_that_changed:
                filename = file[2]
                filepath = file[0]
                # Delete all entries with this filename and path
                FileInfo.objects.filter(filename=filename, absolute_path=filepath).delete()

            # Then delete from AnythingLLM
            self.delete_files_from_anythingLLM(files_that_changed)
            # Finally add the new versions
            self.add_files_to_anythingLLM(files_that_changed)
        except Exception as e:
            print(f"Error updating files: {str(e)}")

    def update_workspace_embeddings(self, list_of_new_embeddings):
        # -----------------------------
        # This function embeds the uploaded documents in the workspaces with 1 api call.
        # list_of_new_embeddings has arrays of this structure: [folder_name, only_file_name]
        # We go through every object and make a dict for each workspace that needs new embeddings.
        # Then we make an API call for each workspace to update the embeddings.
        # -----------------------------
        try:
            # Check if CREATE_WORKSPACES is enabled and print log message if not
            if not (os.getenv("CREATE_WORKSPACES", "true").lower() in ("1", "true", "yes")):
                if self.verbose:
                    print(f"Skipping workspace creation because CREATE_WORKSPACES is disabled.")

            checked_workspaces = []
            workspaces_to_update = {}
            for workspace in list_of_new_embeddings:
                workspace_name = workspace[0]
                if workspace_name not in checked_workspaces:  # check or create workspace
                    response = requests.get(
                        url=self.main_url
                        + self.get_workspace_url
                        + workspace_name.lower().replace(" ", "-"),
                        headers=self.headers_json,
                        timeout=120,
                        verify=False
                    )
                    if len(response.json()["workspace"]) == 0:
                        self._create_workspace_if_not_exists(workspace_name)

                # now lets create the array which we will send to the API to update embeddings for the workspaces
                file_name = workspace[1]
                if workspace_name in workspaces_to_update:
                    workspaces_to_update[workspace_name].append(
                        f"{workspace_name}/{file_name}"
                    )
                else:
                    workspaces_to_update[workspace_name] = [f"{workspace_name}/{file_name}"]
            if self.verbose: print(f"Workspaces to update: {workspaces_to_update}")
            for key, val in workspaces_to_update.items():
                if self.verbose: print(val)
                json_to_send = {
                    "adds": val,
                    "deletes": [],
                }  # deletes is empty because we only delete files, which also deletes embeddings
                requests.post(
                    url=self.main_url
                    + self.get_workspace_url
                    + key.lower().replace(" ", "-")
                    + self.update_embeddings_url,
                    headers=self.headers_json,
                    json=json_to_send,
                    timeout=120,
                    verify=False
                )
        except Exception as e:
            print(f"Error updating embeddings: {str(e)}")

    def delete_unused_workspaces(self):
        # -----------------------------
        # This function deletes workspaces with no documents embedded in them.
        # But only those workspaces get deleted, if they were created by this program and are in the database.
        # -----------------------------
        try:
            all_created_workspaces = created_workspaces.objects.all()
            for workspace in all_created_workspaces:
                response = requests.get(
                    url=self.main_url
                    + self.get_workspace_url
                    + str.lower(workspace.name).replace(" ", "-"),
                    headers=self.headers_json,
                    timeout=120,
                    verify=False
                )
                workspace_data = response.json()["workspace"]
                if len(workspace_data) != 0:
                    this_workspace = workspace_data[0]
                    if len(this_workspace["documents"]) == 0:
                        requests.delete(
                            url=self.main_url
                            + self.get_workspace_url
                            + str.lower(workspace.name).replace(" ", "-"),
                            headers=self.headers_json,
                            timeout=120,
                            verify=False
                        )
                        workspace.delete()
        except Exception as e:
            print(f"Error for deleting old workspaces {str(e)}")

    def delete_unused_folders(self):
        # -----------------------------
        # This function deletes empty folders from AnythingLLM
        # -----------------------------
        try:
            response = requests.get(self.main_url + self.get_documents_url, headers=self.headers_json, timeout=120, verify=False)
            folders = response.json()["localFiles"]["items"]
            for folder in folders:
                
                if folder["name"] == "custom-documents": #we skip this basic folder since it always gets regenerated
                    continue

                if len(folder["items"]) == 0:
                    json_to_send = {
                        "name": folder["name"]
                    }
                    requests.delete(self.main_url + self.delete_folder_url, headers=self.headers_json, json=json_to_send, timeout=120, verify=False)
                    if self.verbose: print(f"Deleted folder: {folder['name']}")
        except Exception as e:
            print(f"Error deleting unused folders: {str(e)}")

    def _create_workspace_if_not_exists(self, workspace_name):
        # Check if CREATE_WORKSPACES is enabled and skip creation if not
        if not (os.getenv("CREATE_WORKSPACES", "true").lower() in ("1", "true", "yes")):
            return

        try:
            if self.verbose: print(
                f" {workspace_name} did not exist as a workspace, so we create one"
            )
            new_workspace_json = {
                "name": f"🔄{workspace_name}",
                "similarityThreshold": 0.25,
                "openAiTemp": 0.7,
                "openAiHistory": 20,
                "openAiPrompt": "Given the following conversation, relevant context, and a follow up question, reply with an answer to the current question the user is asking. Return only your response to the question given the above information following the users instructions as needed.",
                "queryRefusalResponse": "There is no relevant information in this workspace to answer your query.",
                "chatMode": "chat",
                "topN": 4,
            }

            created_workspaces.objects.create(name=workspace_name)

            if self.verbose: print(f"Creating new workspace: {workspace_name}")
            response = requests.post(
                url=self.main_url + self.new_workspace_url,
                headers=self.headers_json,
                json=new_workspace_json,
                timeout=120,
                verify=False
            )
            if self.verbose: print(f"Workspace {workspace_name} created, response: {response.json()}")
        except Exception as e:
            print(f"Error creating workspace: {str(e)}")

    def _saveFile(self, file_path, main_folder):
        try:
            # First ensure any existing entries are removed
            FileInfo.objects.filter(
                filename=os.path.basename(file_path),
                absolute_path=os.path.abspath(file_path),
            ).delete()

            # Now create the new entry
            creation_time = os.path.getctime(file_path)
            modification_time = os.path.getmtime(file_path)
            found_created_at = timezone.make_aware(datetime.fromtimestamp(creation_time))
            found_modified_at = timezone.make_aware(
                datetime.fromtimestamp(modification_time)
            )

            return FileInfo.objects.create(
                filename=os.path.basename(file_path),
                absolute_path=os.path.abspath(file_path),
                main_folder=main_folder,
                file_size=os.path.getsize(file_path),
                created_at=found_created_at,
                modified_at=found_modified_at,
            )
        except Exception as e:
            print(f"Error saving files sources in DB {str(e)}")


def main():
    verbose = os.environ.get("VERBOSE", "false").lower() == "true"
    if not verbose:
        verbose = False

    file_scanner = FileScanner(verbose=verbose)
    if verbose: print(f"Host folders: {file_scanner.host_folders}")
    files_to_add, files_that_changed, files_got_deleted  = file_scanner.scan_files()
    anythingLLM_api_client = AnythingLLM_API_Client(verbose=verbose)
    anythingLLM_api_client.update(files_to_add=files_to_add, files_that_changed=  files_that_changed, files_got_deleted= files_got_deleted,)
    file_scanner.reset()
    anythingLLM_api_client.reset()
    
    # Sort files in AnythingLLM
    if os.environ.get("SORT_FILES") == "true":
        sort_files = SortFiles(verbose=verbose)
        sort_files.sort_files()
        sort_files.reset()
    if os.environ.get("DELETE_UNUSED_FOLDERS") == "true":
        anythingLLM_api_client.delete_unused_folders()

    return f"Files added: {len(files_to_add)}, Files changed: {len(files_that_changed)}, Files deleted: {len(files_got_deleted)}. File system got organized."

if __name__ == "__main__":
    main()
