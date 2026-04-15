from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import uuid
from enum import Enum
from .config import MesaVersion, require_active_config
from .options import Inlist

class ModelState(Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Model:
    """Class that represents a MESA model with its inlists, execution files, IDs etc.

    Attributes:
        name: Name of the model, which will be the name of the model directory.
        model_id: Hexadecimal identification number for the model.
        state: ModelState representing whether the model is running, failed, finished etc.
        mesa_version: The MESA version used to prepare and run this model.
        inlists: Dictionary of Inlist objects associated with this model.
        model_path: Path to the location of the model directory.
        created_at: Datetime object representing the creation date and time of this Model object.
        started_at: Datetime object representing date and time at which this model started running.
        updated_at: Datetime object representing date and time at which the ModelState or Model attributes changed.
        finished_at: Datetime object representing the date and time at which the model finished running.
        file_snapshot: Dictionary containing relative paths of files at model_path. 
            Used to track changes between inlists at model_path and in Model.inlists
            and only set when work_setup.create_modeldir is called with this instance
            as an argument.
        snapshot_at: datetime object to store at which moment a file_snapshot is taken. 
            Only set when work_setup.create_modeldir is called with this instance
            as an argument.

    """

    name: str
    model_path: Path | None = None
    mesa_version: MesaVersion | None = None
    model_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: ModelState = field(default=ModelState.DRAFT)
    inlists: dict[str, Inlist] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    file_snapshot: dict[str, str] = field(default_factory=dict)
    snapshot_taken_at: datetime | None = None

    def __post_init__(self) -> None:
        """Method looking for mesa_version from active MesaConfig if mesa_version is not specified.
        """
        if self.mesa_version is None:
            self.mesa_version = require_active_config().mesa_version

    def add_inlist(self, inlist: Inlist) -> None:
        """Method to add an Inlist object to the inlists attribute.

        Args:
            inlist: Inlist opject to be added to the Model.inlist attribute.
        Returns:
            None
        """

        self.inlists[inlist.name] = inlist
    
    def remove_inlist(self, inlist_name: str) -> bool:
        """Method to remove an Inlist object from the inlists attribute.

        Agrs:
            inlist_name: Name of the Inlist object to be removed from the 
                inlists attribute
        Returns:
            Boolean, True if removed, false if not present and, therefore, not removed
        """
        is_removed = self.inlists.pop(inlist_name, None)
        return is_removed is not None
    
    @classmethod
    def empty(cls, name: str, mesa_version: MesaVersion | None = None) -> "Model":
        """Method to initiate and empty Model object which can be populated later.

        Args:
            name: Name for this Model object, which will be the directory name when writing 
                out the Model object to the storage.
            mesa_version: MesaVersion of the Model object
            
        Returns:
            Model object
        """
        return cls(name=name, mesa_version=mesa_version)
    
    def return_log_directory_paths(self) -> dict:
        '''Function that returns a dictionary containing all the LOGS directories specified in the inlists
            that are part of Model.inlists.
        Args:
            self
        Returns:
            - Dictionary with locations to LOGS directories and the associated inlists
            - Model.model_dir / LOGS or LOGS1 & LOGS 2 if no logs directories are specified in the inlists
            - An empty dictionary is the Model.inlists dictionary is empty
        '''
        log_dirs = {}
        if bool(self.inlists):
            return log_dirs
        #TODO
    

#TODO: Implement tests for this module.