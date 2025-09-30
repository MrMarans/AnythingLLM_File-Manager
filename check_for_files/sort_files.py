import requests
import urllib3
import os
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class SortFiles:
    def __init__(self, verbose=True):
        self.AnythingLLM_api = os.environ.get("ANYTHING_LLM_API")
        if not self.AnythingLLM_api:
            raise ValueError("ANYTHING_LLM_API environment variable is not set")
        self.headers_json = {  #Header for most request types
            "accept": "application/json",
            "Authorization": f"Bearer {self.AnythingLLM_api}",
            "Content-Type": "application/json",
        }
        self.verbose = verbose
        self.embedded_documents = {}
        
        self.main_url = os.environ.get("ANYTHING_LLM_URL")
        if not self.main_url:
            raise ValueError("ANYTHING_LLM_URL environment variable is not set")

    def reset(self) -> None:
        self.embedded_documents = {}

    def _get_folders_list(self) -> list[str]:
        response = requests.get(f"{self.main_url}/api/v1/documents", headers=self.headers_json, timeout=10, verify=False).json()
        localFiles = response["localFiles"]
        folders = localFiles["items"]
        all_folders = []
        for folder in folders:
            folder_name = folder["name"]
            all_folders.append(folder_name)
        return all_folders

    def _change_embedding(self, workspace, add, delete) -> None:
        if add != delete:
            json_to_send = {
                        "adds": add,
                        "deletes": delete
                    }
            if self.verbose: print(f"json_to_send embedding: {json_to_send}")
            response = requests.post(f"{self.main_url}/api/v1/workspace/{workspace}/update-embeddings", headers=self.headers_json, timeout=10, verify=False, json=json_to_send)

    def _move_document(self, docpath, docname, folder_name) -> str:
        new_path = folder_name + "/" + docname
        json_to_send = {
            "files": [
                {
                    "from": docpath,
                    "to": new_path
                }
            ]
        }
        if self.verbose: print(f"json_to_send: {json_to_send}")
        response = requests.post(f"{self.main_url}/api/v1/document/move-files", headers=self.headers_json, timeout=10, verify=False, json=json_to_send)
        return new_path

    def _change_pinning(self, workspace: str, docpath: str) -> None:
        """
        Update the pin status of a document in a workspace.
        
        Args:
            workspace (str): The workspace slug where the document is located
            docpath (str): The path to the document
        """
        json_to_send = {
            "docPath": docpath,
            "pinStatus": True  # We set it to True since we're handling pinned documents
        }
        if self.verbose: print(f"json_to_send pinning: {json_to_send}")
        response = requests.post(
            f"{self.main_url}/api/v1/workspace/{workspace}/update-pin",
            headers=self.headers_json,
            timeout=10,
            verify=False,
            json=json_to_send
        )
        if response.status_code not in [200, 201]:
            if self.verbose: print(f"Failed to update pin status for {docpath} in workspace {workspace}. Status code: {response.status_code}")

    def sort_files(self) -> None:
        # step 1: get all embedded documents
        response = requests.get(f"{self.main_url}/api/v1/workspaces", headers=self.headers_json, timeout=10, verify=False).json()
        workspaces = response["workspaces"]
        for workspace in workspaces:
            response = requests.get(f"{self.main_url}/api/v1/workspace/{workspace['slug']}", headers=self.headers_json, timeout=10, verify=False).json()
            workspace = response["workspace"][0]
            documents = workspace["documents"]
            for doc in documents:
                if doc["filename"] in self.embedded_documents:
                    self.embedded_documents[doc["filename"]]["in_workspaces"].append(workspace["slug"])
                else:
                    self.embedded_documents[doc["filename"]] = {"in_workspaces": [workspace["slug"]], "path": doc["docpath"], "pinning": {workspace["slug"]: doc["pinned"]}}

        if self.verbose: print("embedded_documents: ", self.embedded_documents)

        #step 2: remove embeddings
        for doc in self.embedded_documents:
            if len(self.embedded_documents[doc]["in_workspaces"]) !=0:
                if self.verbose:print(f"doc {doc} is in workspaces {self.embedded_documents[doc]['in_workspaces']}")
                # remove the embedding from the document
                for workspace in self.embedded_documents[doc]["in_workspaces"]:
                    self._change_embedding(workspace, add=[], delete=[self.embedded_documents[doc]['path']])

        files_moved = 0
        # step 3: check folders for embedded documents
        all_folders = self._get_folders_list()
        for doc in self.embedded_documents:
            if len(self.embedded_documents[doc]["in_workspaces"]) == 1:
                if self.verbose: print("doc is in one workspace")
                new_foldername = self.embedded_documents[doc]["in_workspaces"][0]
                if self.verbose:print(f"new foldername: {new_foldername}")

                if new_foldername not in all_folders:
                    response = requests.post(f"{self.main_url}/api/v1/document/create-folder", headers=self.headers_json, timeout=10, verify=False, json={"name": new_foldername}).json()
                new_path = self._move_document(self.embedded_documents[doc]["path"], doc, new_foldername)
                self._change_embedding(self.embedded_documents[doc]["in_workspaces"][0], add=[new_path], delete=[])

                

                files_moved += 1
            elif len(self.embedded_documents[doc]["in_workspaces"]) > 1:
                if self.verbose: print("Documents is in multiple workspaces")
                print("Documents in multiple workspaces are not yet supported for reordering")
            else:
                if self.verbose: print("Document is not in any workspace")

        # step 4: check for pinned documents
        for doc in self.embedded_documents:
            if self.embedded_documents[doc]["pinning"]:
                for workspace in self.embedded_documents[doc]["pinning"]:
                    if self.embedded_documents[doc]["pinning"][workspace]:
                        self._change_pinning(workspace, self.embedded_documents[doc]["path"])

        if self.verbose: print(f"Files moved: {files_moved}")
        return files_moved

if __name__ == "__main__":
    sort_files = SortFiles()
    sort_files.sort_files()
    sort_files.reset()