from data_engine.dataset_manager import dataset_manager


def get_current_dataset():
    """
    Return the dataset currently loaded by the application.
    """

    return dataset_manager.get_dataframe()


def get_current_dataset_name():
    """
    Return the filename of the currently loaded dataset.
    """

    return dataset_manager.get_filename()


def has_dataset_loaded():
    """
    Check whether a dataset is currently available.
    """

    return dataset_manager.is_loaded()
