import numpy as np
from copy import deepcopy
from pathlib import Path
import json

from deeppavlov.models.evolution.utils import find_index_of_dict_with_key_in_pipe
from deeppavlov.core.common.file import read_json
from deeppavlov.core.common.log import get_logger


log = get_logger(__name__)


class ParamsEvolution:
    """
    Class performs full evolutionary process (task scores -> max):
    1. initializes random population
    2. makes replacement to get next generation:
        a. selection according to obtained scores
        b. crossover (recombination) with given probability p_crossover
        c. mutation with given mutation rate p_mutation (probability to mutate)
            according to given mutation power sigma
            (current mutation power is randomly from -sigma to sigma)
    """

    def __init__(self,
                 population_size,
                 p_crossover=0.5, crossover_power=0.5,
                 p_mutation=0.5, mutation_power=0.1,
                 key_main_model="main",
                 seed=None,
                 train_partition=1,
                 elitism_with_weights=False,
                 **kwargs):
        """
        Initialize evolution with random population
        Args:
            population_size: number of individuums per generation
            p_crossover: probability to cross over for current replacement
            crossover_power: part of EVOLVING parents parameters to exchange for offsprings
            p_mutation: probability of mutation for current replacement
            mutation_power: allowed percentage of mutation
            key_model_to_evolve: binary flag that should be inserted into the dictionary
                        with main model in the basic config (to determine save and load paths that will be changed)
            seed: random seed for initialization
            train_partition: integer number of train data parts
            **kwargs: basic config with parameters
        """

        self.basic_config = deepcopy(kwargs)
        self.main_model_path = list(self._find_model_path(self.basic_config, key_main_model))[0]
        Path(self._get_value_from_config(self.basic_config, self.main_model_path + ["save_path"])).mkdir(parents=True,
                                                                                                         exist_ok=True)
        self.print_dict(self.basic_config, string="Basic config:")
        log.info("Main model path in config: {}".format(self.main_model_path))

        self.population_size = population_size
        self.p_crossover = p_crossover
        self.p_mutation = p_mutation
        self.mutation_power = mutation_power
        self.crossover_power = crossover_power
        self.elitism_with_weights = elitism_with_weights

        self.n_saved_best_pretrained = 0
        self.train_partition = train_partition

        self.paths_to_evolving_params = []
        for evolve_type in ["evolve_range", "evolve_choice", "evolve_bool"]:
            for path_ in self._find_model_path(self.basic_config, evolve_type):
                self.paths_to_evolving_params.append(path_)

        self.n_evolving_params = len(self.paths_to_evolving_params)
        self.evolution_model_id = 0

        if seed is None:
            pass
        else:
            np.random.seed(seed)

    def _find_model_path(self, config, key_model, path=[]):
        """
        Find path to the main model in config which paths will be changed
        Args:
            config:
            key_model:

        Returns:
            path in config -- list of keys (strings and integers)
        """
        config_pointer = config
        if type(config_pointer) is dict and key_model in config_pointer.keys():
            # main model is an element of chainer.pipe list
            # main model is a dictionary and has key key_main_model
            yield path
        else:
            if type(config_pointer) is dict:
                for key in list(config_pointer.keys()):
                    for path_ in self._find_model_path(config_pointer[key], key_model, path + [key]):
                        yield path_
            elif type(config_pointer) is list:
                for i in range(len(config_pointer)):
                    for path_ in self._find_model_path(config_pointer[i], key_model, path + [i]):
                        yield path_

    @staticmethod
    def _insert_value_or_dict_into_config(config, path, value):
        config_copy = deepcopy(config)
        config_pointer = config_copy
        for el in path[:-1]:
            if type(config_pointer) is dict:
                config_pointer = config_pointer.setdefault(el, {})
            elif type(config_pointer) is list:
                config_pointer = config_pointer[el]
            else:
                pass
        config_pointer[path[-1]] = value
        return config_copy

    @staticmethod
    def _get_value_from_config(config, path):
        config_copy = deepcopy(config)
        config_pointer = config_copy
        for el in path[:-1]:
            if type(config_pointer) is dict:
                config_pointer = config_pointer.setdefault(el, {})
            elif type(config_pointer) is list:
                config_pointer = config_pointer[el]
            else:
                pass
        return config_pointer[path[-1]]

    @staticmethod
    def print_dict(config, string=None):
        if string is None:
            log.info(json.dumps(config, indent=2))
        else:
            log.info(string)
            log.info(json.dumps(config, indent=2))
        return None

    def initialize_params_in_config(self, basic_config, paths):
        config = deepcopy(basic_config)

        for path_ in paths:
            param_name = path_[-1]
            value = self._get_value_from_config(basic_config, path_)
            if type(value) is dict:
                if value.get("evolve_choice"):
                    config = self._insert_value_or_dict_into_config(config,
                                                                    path_,
                                                                    self.sample_params(
                                                                        **{param_name:
                                                                               list(value["values"])})[param_name])
                elif value.get("evolve_range"):
                    config = self._insert_value_or_dict_into_config(config,
                                                                    path_,
                                                                    self.sample_params(
                                                                        **{param_name:
                                                                               deepcopy(value)})[param_name])
                elif value.get("evolve_bool"):
                    config = self._insert_value_or_dict_into_config(config,
                                                                    path_,
                                                                    self.sample_params(
                                                                        **{param_name:
                                                                               deepcopy(value)})[param_name])

        return config

    def first_generation(self, iteration=0):
        """
        Initialize first generation randomly according to the given constraints is self.params
        Returns:
            first generation that consists of self.population_size individuums
        """
        population = []
        for i in range(self.population_size):
            population.append(self.initialize_params_in_config(self.basic_config, self.paths_to_evolving_params))
            for which_path in ["save_path", "load_path"]:
                population[-1] = self._insert_value_or_dict_into_config(population[-1],
                                                                        self.main_model_path + [which_path],
                                                                        str(Path(
                                                                            self.basic_config["save_path"]).joinpath(
                                                                            "population_" + str(iteration)).joinpath(
                                                                            "model_" + str(i))))
            population[-1]["evolution_model_id"] = self.evolution_model_id
            self.evolution_model_id += 1

        return population

    def next_generation(self, generation, scores, iteration,
                        p_crossover=None, crossover_power=None,
                        p_mutation=None, mutation_power=None):
        """
        Provide an operation of replacement
        Args:
            generation: current generation (set of self.population_size configs
            scores: corresponding scores that should be maximized
            iteration: iteration number
            p_crossover: probability to cross over for current replacement
            crossover_power: part of parents parameters to exchange for offsprings
            p_mutation: probability of mutation for current replacement
            mutation_power: allowed percentage of mutation

        Returns:
            the next generation according to the given scores of current generation
        """
        if not p_crossover:
            p_crossover = self.p_crossover
        if not crossover_power:
            crossover_power = self.crossover_power
        if not p_mutation:
            p_mutation = self.p_mutation
        if not mutation_power:
            mutation_power = self.mutation_power

        next_population = self.selection_of_best_with_weights(generation, scores)
        print("Saved with weights: {} individuums".format(self.n_saved_best_pretrained))
        offsprings = self.crossover(generation, scores,
                                    p_crossover=p_crossover,
                                    crossover_power=crossover_power)

        changable_next = self.mutation(offsprings,
                                       p_mutation=p_mutation,
                                       mutation_power=mutation_power)

        next_population.extend(changable_next)

        for i in range(self.n_saved_best_pretrained):
            # if several train files:
            if self.train_partition != 1:
                next_population[i]["dataset_reader"]["train"] = "_".join(str(Path(next_population[i]["dataset_reader"][
                                                                                      "train"]).stem.split("_")[:-1])) \
                                                                + "_" + str(iteration % self.train_partition) + ".csv"
            try:
                # re-init learning rate with the final one (works for KerasModel)
                next_population[i] = self._insert_value_or_dict_into_config(
                    next_population[i],
                    self._get_value_from_config(next_population[i],
                                                self.main_model_path + ["lear_rate"]),
                    read_json(str(Path(self._get_value_from_config(next_population[i],
                                                                   self.main_model_path + ["save_path"])
                                       ).parent.joinpath("model_opt.json")))["final_lear_rate"])
            except:
                pass

            if self.elitism_with_weights:
                # if elite models are saved with weights
                next_population[i] = self._insert_value_or_dict_into_config(
                    next_population[i],
                    self._get_value_from_config(next_population[i],
                                                self.main_model_path + ["load_path"]),
                    str(Path(self._get_value_from_config(next_population[i],
                                                         self.main_model_path + ["save_path"])).parent))
            else:
                # if elite models are saved only as configurations and trained again
                next_population[i] = self._insert_value_or_dict_into_config(
                    next_population[i],
                    self._get_value_from_config(next_population[i],
                                                self.main_model_path + ["load_path"]),
                    str(Path(self._get_value_from_config(next_population[i], self.main_model_path + ["load_path"])
                             ).joinpath("population_" + str(iteration)).joinpath("model_" + str(i))))

            next_population[i] = self._insert_value_or_dict_into_config(
                next_population[i],
                self._get_value_from_config(next_population[i],
                                            self.main_model_path + ["save_path"]),
                str(Path(self._get_value_from_config(next_population[i], self.main_model_path + ["save_path"])
                         ).joinpath("population_" + str(iteration)).joinpath("model_" + str(i))))

        for i in range(self.n_saved_best_pretrained, self.population_size):
            # if several train files
            if self.train_partition != 1:
                next_population[i]["dataset_reader"]["train"] = "_".join(str(Path(next_population[i]["dataset_reader"][
                                                                                  "train"]).stem.split("_")[:-1])) \
                                                            + "_" + str(iteration % self.train_partition) + ".csv"
            for which_path in ["save_path", "load_path"]:
                next_population[i] = self._insert_value_or_dict_into_config(
                    next_population[i],
                    self._get_value_from_config(next_population[i],
                                                self.main_model_path + [which_path]),
                    str(Path(self._get_value_from_config(next_population[i], self.main_model_path + [which_path])
                             ).joinpath("population_" + str(iteration)).joinpath("model_" + str(i))))

            next_population[i]["evolution_model_id"] = self.evolution_model_id
            self.evolution_model_id += 1

        return next_population

    def selection_of_best_with_weights(self, population, scores):
        """
        Select individuums to save with weights for the next generation from given population.
        Range is an order of an individuum within sorted scores (1 range = max-score, self.population_size = min-score)
        Individuum with the highest score has probability equal to 1 (100%).
        Individuum with the lowest score has probability equal to 0 (0%).
        Probability of i-th individuum to be selected with weights is (a * range_i + b)
        where a = 1. / (1. - self.population_size), and
        b = self.population_size / (self.population_size - 1.)
        Args:
            population: self.population_size individuums
            scores: corresponding score that should be maximized

        Returns:
            selected self.n_saved_best_pretrained (changable) individuums
        """
        scores = np.array(scores, dtype='float')
        sorted_ids = np.argsort(scores)
        ranges = np.array([self.population_size - np.where(i == sorted_ids)[0][0]
                           for i in np.arange(self.population_size)])

        a = 1. / (1. - self.population_size)
        b = self.population_size / (self.population_size - 1.)
        probas_to_be_selected = a * ranges + b

        selected = []
        for i in range(self.population_size):
            if self.decision(probas_to_be_selected[i]):
                selected.append(deepcopy(population[i]))

        self.n_saved_best_pretrained = len(selected)
        return selected

    def crossover(self, population, scores, p_crossover, crossover_power):
        """
        Recombine randomly population in pairs and cross over them with given probability.
        Cross over from two parents produces two offsprings
        each of which contains crossover_power portion of the parameter values from one parent,
         and the other (1 - crossover_power portion) from the other parent
        Args:
            population: self.population_size individuums
            p_crossover: probability to cross over for current replacement
            crossover_power: part of EVOLVING parents parameters to exchange for offsprings

        Returns:
            (self.population_size - self.n_saved_best_pretained) offsprings
        """
        offsprings = []
        scores = np.array(scores, dtype='float')
        probas_to_be_parent = scores / np.sum(scores)
        intervals = np.array([np.sum(probas_to_be_parent[:i]) for i in range(self.population_size)])

        for i in range(self.population_size - self.n_saved_best_pretrained):
            rs = np.random.random(2)
            parents = population[np.where(rs[0] > intervals)[0][-1]], population[np.where(rs[1] > intervals)[0][-1]]

            if self.decision(p_crossover):
                params_perm = np.random.permutation(self.n_evolving_params)

                curr_offsprings = [deepcopy(parents[0]),
                                   deepcopy(parents[1])]

                part = int(crossover_power * self.n_evolving_params)

                for j in range(self.n_evolving_params - part, self.n_evolving_params):
                    curr_offsprings[0] = self._insert_value_or_dict_into_config(curr_offsprings[0],
                                                                                self.paths_to_evolving_params[
                                                                                    params_perm[j]],
                                                                                self._get_value_from_config(
                                                                                    parents[1],
                                                                                    self.paths_to_evolving_params[
                                                                                        params_perm[j]]))

                    curr_offsprings[1] = self._insert_value_or_dict_into_config(curr_offsprings[1],
                                                                                self.paths_to_evolving_params[
                                                                                    params_perm[j]],
                                                                                self._get_value_from_config(
                                                                                    parents[0],
                                                                                    self.paths_to_evolving_params[
                                                                                        params_perm[j]]))
                offsprings.append(deepcopy(curr_offsprings[0]))
            else:
                offsprings.append(deepcopy(parents[0]))

        return offsprings

    def mutation(self, population, p_mutation, mutation_power):
        """
        Mutate each parameter of each individuum in population with probability p_mutation
        Args:
            population: self.population_size individuums
            p_mutation: probability to mutate for each parameter
            mutation_power: allowed percentage of mutation

        Returns:
            mutated population
        """
        mutated = []

        for individuum in population:
            mutated_individuum = deepcopy(individuum)

            # mutation of dataset iterator params
            for param in self.dataset_iterator_params.keys():
                mutated_individuum["dataset_iterator"][param] = \
                    self.mutation_of_param(param, self.dataset_iterator_params,
                                           individuum["dataset_iterator"][param],
                                           p_mutation, mutation_power)

            # mutation of other model params
            for param in self.params.keys():
                mutated_individuum["chainer"]["pipe"][self.model_to_evolve_index][param] = \
                    self.mutation_of_param(param, self.params,
                                           individuum["chainer"]["pipe"][self.model_to_evolve_index][param],
                                           p_mutation, mutation_power)

            # mutation of train params
            for param in self.train_params.keys():
                mutated_individuum["train"][param] = \
                    self.mutation_of_param(param, self.train_params,
                                           individuum["train"][param],
                                           p_mutation, mutation_power)

            mutated.append(mutated_individuum)

        return mutated

    def mutation_of_param(self, param, params_dict, param_value, p_mutation, mutation_power):
        new_mutated_value = deepcopy(param_value)
        if self.decision(p_mutation):
            if type(params_dict[param]) is dict:
                if params_dict[param].get('discrete', False):
                    val = round(param_value +
                                ((2 * np.random.random() - 1.) * mutation_power
                                 * self.sample_params(**{param: params_dict[param]})[param]))
                    val = min(max(params_dict[param]["evolve_range"][0], val),
                              params_dict[param]["evolve_range"][1])
                    new_mutated_value = val
                elif 'evolve_range' in params_dict[param].keys():
                    val = param_value + \
                          ((2 * np.random.random() - 1.) * mutation_power
                           * self.sample_params(**{param: params_dict[param]})[param])
                    val = min(max(params_dict[param]["evolve_range"][0], val),
                              params_dict[param]["evolve_range"][1])
                    new_mutated_value = val
                elif params_dict[param].get("evolve_choice"):
                    # new_mutated_value = param_value
                    new_mutated_value = self.sample_params(**{param: params_dict[param]})[param]
                else:
                    new_mutated_value = param_value
            else:
                new_mutated_value = param_value
        else:
            new_mutated_value = param_value

        return new_mutated_value

    def decision(self, probability):
        """
        Make decision whether to do action or not with given probability
        Args:
            probability: probability whether

        Returns:

        """
        r = np.random.random()
        if r < probability:
            return True
        else:
            return False

    def sample_params(self, **params):
        if not params:
            return {}
        else:
            params_copy = deepcopy(params)
        params_sample = dict()
        for param, param_val in params_copy.items():
            if isinstance(param_val, list):
                params_sample[param] = np.random.choice(param_val)
            elif isinstance(param_val, dict):
                if 'evolve_bool' in param_val and param_val['evolve_bool']:
                    sample = bool(np.random.choice([True, False]))
                elif 'evolve_range' in param_val:
                    sample = self._sample_from_ranges(param_val)
                params_sample[param] = sample
            else:
                params_sample[param] = params_copy[param]
        return params_sample

    def _sample_from_ranges(self, opts):
        from_ = opts['evolve_range'][0]
        to_ = opts['evolve_range'][1]
        if opts.get('scale', None) == 'log':
            sample = self._sample_log(from_, to_)
        else:
            sample = np.random.uniform(from_, to_)
        if opts.get('discrete', False):
            sample = int(np.round(sample))
        return sample

    @staticmethod
    def _sample_log(from_, to_):
        sample = np.exp(np.random.uniform(np.log(from_), np.log(to_)))
        return float(sample)