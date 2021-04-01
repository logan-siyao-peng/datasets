import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# loading package files: https://stackoverflow.com/a/20885799
try:
    import importlib.resources as pkg_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources as pkg_resources

import langcodes as lc
import yaml

from . import resources


BASE_REF_URL = "https://github.com/huggingface/datasets/tree/master/src/datasets/utils"
this_url = f"{BASE_REF_URL}/{__file__}"
logger = logging.getLogger(__name__)


def load_json_resource(resource: str) -> Tuple[Any, str]:
    content = pkg_resources.read_text(resources, resource)
    return json.loads(content), f"{BASE_REF_URL}/resources/{resource}"


known_licenses, known_licenses_url = load_json_resource("licenses.json")
known_task_ids, known_task_ids_url = load_json_resource("tasks.json")
known_creators, known_creators_url = load_json_resource("creators.json")
known_size_categories, known_size_categories_url = load_json_resource("size_categories.json")
known_multilingualities, known_multilingualities_url = load_json_resource("multilingualities.json")


def dict_from_readme(f: Path) -> Optional[Dict[str, List[str]]]:
    with f.open() as fi:
        content = [line.strip() for line in fi]

    if content[0] == "---" and "---" in content[1:]:
        yamlblock = "\n".join(content[1 : content[1:].index("---") + 1])
        metada_dict = yaml.safe_load(yamlblock) or dict()
        return metada_dict


ValidatorOutput = Tuple[List[str], Optional[str]]


def tagset_validator(values: List[str], reference_values: List[str], name: str, url: str) -> ValidatorOutput:
    invalid_values = [v for v in values if v not in reference_values]
    if len(invalid_values) > 0:
        return [], f"{invalid_values} are not registered tags for '{name}', reference at {url}"
    return values, None


def escape_validation_for_predicate(
    values: List[Any], predicate_fn: Callable[[Any], bool]
) -> Tuple[List[Any], List[Any]]:
    trues, falses = list(), list()
    for v in values:
        if predicate_fn(v):
            trues.append(v)
        else:
            falses.append(v)
    if len(trues) > 0:
        logger.warning(f"The following values will escape validation: {trues}")
    return trues, falses


@dataclass
class DatasetMetadata:
    annotations_creators: List[str]
    language_creators: List[str]
    languages: List[str]
    licenses: List[str]
    multilinguality: List[str]
    size_categories: List[str]
    source_datasets: List[str]
    task_categories: List[str]
    task_ids: List[str]

    def __post_init__(self):
        basic_typing_errors = {
            name: value
            for name, value in vars(self).items()
            if not isinstance(value, list) or len(value) == 0 or not isinstance(value[0], str)
        }
        if len(basic_typing_errors) > 0:
            raise TypeError(f"Found fields that are not non-empty list of strings: {basic_typing_errors}")

        self.annotations_creators, annotations_creators_errors = self.annotations_creators_must_be_in_known_set(
            self.annotations_creators
        )
        self.language_creators, language_creators_errors = self.language_creators_must_be_in_known_set(
            self.language_creators
        )
        self.languages, languages_errors = self.language_code_must_be_recognized(self.language_creators)
        self.licenses, licenses_errors = self.licenses_must_be_in_known_set(self.licenses)
        self.multilinguality, multilinguality_errors = self.multilinguality_must_be_in_known_set(self.multilinguality)
        self.size_categories, size_categories_errors = self.size_categories_must_be_in_known_set(self.size_categories)
        self.source_datasets, source_datasets_errors = self.source_datasets_must_be_in_known_set(self.source_datasets)
        self.task_categories, task_categories_errors = self.task_category_must_be_in_known_set(self.task_categories)
        self.task_ids, task_ids_errors = self.task_id_must_be_in_known_set(self.task_ids)

        errors = {
            "annotations_creators": annotations_creators_errors,
            "language_creators": language_creators_errors,
            "licenses": licenses_errors,
            "multilinguality": multilinguality_errors,
            "size_categories": size_categories_errors,
            "source_datasets": source_datasets_errors,
            "task_categories": task_categories_errors,
            "task_ids": task_ids_errors,
        }

        exception_msg_dict = dict()
        for field, errs in errors.items():
            if errs is not None:
                exception_msg_dict[field] = errs
        if len(exception_msg_dict) > 0:
            raise TypeError(
                "Could not validate the metada, found the following errors:\n"
                + "\n".join(f"* field '{fieldname}':\n\t{err}" for fieldname, err in exception_msg_dict.items())
            )

    @classmethod
    def from_readme(cls, f: Path) -> "DatasetMetadata":
        metadata_dict = dict_from_readme(f)
        if metadata_dict is not None:
            return cls(**metadata_dict)
        else:
            raise TypeError(f"did not find a yaml block in '{f}'")

    @classmethod
    def from_yaml_string(cls, string: str) -> "DatasetMetadata":
        metada_dict = yaml.safe_load(string) or dict()
        return cls(**metada_dict)

    @staticmethod
    def annotations_creators_must_be_in_known_set(annotations_creators: List[str]) -> ValidatorOutput:
        return tagset_validator(annotations_creators, known_creators["annotations"], "annotations", known_creators_url)

    @staticmethod
    def language_creators_must_be_in_known_set(language_creators: List[str]) -> ValidatorOutput:
        return tagset_validator(language_creators, known_creators["language"], "annotations", known_creators_url)

    @staticmethod
    def language_code_must_be_recognized(languages: List[str]) -> ValidatorOutput:
        invalid_values = []
        for code in languages:
            try:
                lc.get(code)
            except lc.tag_parser.LanguageTagError:
                invalid_values.append(code)
        if len(invalid_values) > 0:
            return (
                [],
                f"{invalid_values} are not recognised as valid language codes (BCP47 norm), you can refer to https://github.com/LuminosoInsight/langcodes",
            )
        return languages, None

    @staticmethod
    def licenses_must_be_in_known_set(licenses: List[str]) -> ValidatorOutput:
        others, to_validate = escape_validation_for_predicate(licenses, lambda e: "-other-" in e)
        validated, error = tagset_validator(to_validate, list(known_licenses.keys()), "licenses", known_licenses_url)
        return [*validated, *others], error

    @staticmethod
    def task_category_must_be_in_known_set(task_categories: List[str]) -> ValidatorOutput:
        # TODO: we're currently ignoring all values starting with 'other' as our task taxonomy is bound to change
        #   in the near future and we don't want to waste energy in tagging against a moving taxonomy.
        known_set = list(known_task_ids.keys())
        others, to_validate = escape_validation_for_predicate(task_categories, lambda e: e.startswith("other"))
        validated, error = tagset_validator(to_validate, known_set, "tasks_ids", known_task_ids_url)
        return [*validated, *others], error

    @staticmethod
    def task_id_must_be_in_known_set(task_ids: List[str]) -> ValidatorOutput:
        # TODO: we're currently ignoring all values starting with 'other' as our task taxonomy is bound to change
        #   in the near future and we don't want to waste energy in tagging against a moving taxonomy.
        known_set = [tid for _cat, d in known_task_ids.items() for tid in d["options"]]
        others, to_validate = escape_validation_for_predicate(task_ids, lambda e: "-other-" in e)
        validated, error = tagset_validator(to_validate, known_set, "tasks_ids", known_task_ids_url)
        return [*validated, *others], error

    @staticmethod
    def multilinguality_must_be_in_known_set(multilinguality: List[str]) -> ValidatorOutput:
        others, to_validate = escape_validation_for_predicate(multilinguality, lambda e: e.startswith("other"))
        validated, error = tagset_validator(
            to_validate, list(known_multilingualities.keys()), "multilinguality", known_size_categories_url
        )
        return [*validated, *others], error

    @staticmethod
    def size_categories_must_be_in_known_set(size_cats: List[str]) -> ValidatorOutput:
        return tagset_validator(size_cats, known_size_categories, "size_categories", known_size_categories_url)

    @staticmethod
    def source_datasets_must_be_in_known_set(sources: List[str]) -> ValidatorOutput:
        invalid_values = []
        for src in sources:
            is_ok = src in ["original", "extended"] or src.startswith("extended|")
            if not is_ok:
                invalid_values.append(src)
        if len(invalid_values) > 0:
            return (
                [],
                f"'source_datasets' has invalid values: {invalid_values}, refer to source code to understand {this_url}",
            )

        return sources, None


if __name__ == "__main__":
    from argparse import ArgumentParser

    ap = ArgumentParser(usage="Validate the yaml metadata block of a README.md file.")
    ap.add_argument("readme_filepath")
    args = ap.parse_args()

    readme_filepath = Path(args.readme_filepath)
    DatasetMetadata.from_readme(readme_filepath)