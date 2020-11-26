"""The main module of pyhf."""

import copy
import logging

from . import get_backend, default_backend
from . import exceptions
from . import modifiers
from . import utils
from . import events
from . import probability as prob
from .constraints import gaussian_constraint_combined, poisson_constraint_combined
from .parameters import reduce_paramsets_requirements, ParamViewer
from .tensor.common import _TensorViewer, _tensorviewer_from_sizes
from .mixins import _ChannelSummaryMixin

log = logging.getLogger(__name__)


def _paramset_requirements_from_channelspec(spec, channel_nbins):
    # bookkeep all requirements for paramsets we need to build
    _paramsets_requirements = {}
    # need to keep track in which order we added the constraints
    # so that we can generate correctly-ordered data
    for channel in spec['channels']:
        for sample in channel['samples']:
            if len(sample['data']) != channel_nbins[channel['name']]:
                raise exceptions.InvalidModel(
                    f"The sample {sample['name']:s} has {len(sample['data']):d} bins, but the channel it belongs to ({channel['name']:s}) has {channel_nbins[channel['name']]:d} bins."
                )
            for modifier_def in sample['modifiers']:
                # get the paramset requirements for the given modifier. If
                # modifier does not exist, we'll have a KeyError
                try:
                    paramset_requirements = modifiers.registry[
                        modifier_def['type']
                    ].required_parset(sample['data'], modifier_def['data'])
                except KeyError:
                    log.exception(
                        f"Modifier not implemented yet (processing {modifier_def['type']:s}). Available modifiers: {modifiers.registry.keys()}"
                    )
                    raise exceptions.InvalidModifier()

                # check the shareability (e.g. for shapesys for example)
                is_shared = paramset_requirements['is_shared']
                if not (is_shared) and modifier_def['name'] in _paramsets_requirements:
                    raise ValueError(
                        "Trying to add unshared-paramset but other paramsets exist with the same name."
                    )
                if is_shared and not (
                    _paramsets_requirements.get(
                        modifier_def['name'], [{'is_shared': True}]
                    )[0]['is_shared']
                ):
                    raise ValueError(
                        "Trying to add shared-paramset but other paramset of same name is indicated to be unshared."
                    )
                _paramsets_requirements.setdefault(modifier_def['name'], []).append(
                    paramset_requirements
                )
    return _paramsets_requirements


def _paramset_requirements_from_modelspec(spec, channel_nbins, custom_modifiers_params):
    _paramsets_requirements = _paramset_requirements_from_channelspec(
        spec, channel_nbins
    )
    for req in custom_modifiers_params:
        for k,v in req.items():
            _paramsets_requirements.setdefault(k,[]).append(v)

    # build up a dictionary of the parameter configurations provided by the user
    _paramsets_user_configs = {}
    for parameter in spec.get('parameters', []):
        if parameter['name'] in _paramsets_user_configs:
            raise exceptions.InvalidModel(
                f"Multiple parameter configurations for {parameter['name']} were found."
            )
        _paramsets_user_configs[parameter.pop('name')] = parameter

    _reqs = reduce_paramsets_requirements(
        _paramsets_requirements, _paramsets_user_configs
    )

    _sets = {}
    for param_name, paramset_requirements in _reqs.items():
        paramset_type = paramset_requirements.get('paramset_type')
        paramset = paramset_type(**paramset_requirements)
        _sets[param_name] = paramset

    return _sets

class nominal_helper:
    def __init__(self, config):
        self.mega_samples = {}
        self.config = config

    def append(self,c,s,defined_samp):
        self.mega_samples.setdefault(s,{'name': f'mega_{s}', 'nom': []})
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        self.mega_samples[s]['nom'] += nom

    def apply(self):
        nominal_rates = default_backend.astensor(
            [self.mega_samples[s]['nom'] for s in self.config.samples]
        )
        _nominal_rates = default_backend.reshape(
            nominal_rates,
            (
                1,  # modifier dimension.. nominal_rates is the base
                len(self.config.samples),
                1,  # alphaset dimension
                sum(list(self.config.channel_nbins.values())),
            ),
        )
        return _nominal_rates


class lumi_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self, thismod,nom):
        maskval = True if thismod else False
        mask = [maskval] * len(nom)
        return {'mask': mask}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'mask': []}
        )
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']
        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.lumi.required_parset(
                defined_samp['data'], thismod['data']
        ))

class normfactor_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self, thismod,nom):
        maskval = True if thismod else False
        mask = [maskval] * len(nom)
        return {'mask': mask}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'mask': []}
        )
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']
        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.normfactor.required_parset(
                defined_samp['data'], thismod['data']
        ))

class shapefactor_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self, thismod,nom):
        maskval = True if thismod else False
        mask = [maskval] * len(nom)
        return {'mask': mask}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'mask': []}
        )
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']
        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.shapefactor.required_parset(
                defined_samp['data'], thismod['data']
        ))

class shapesys_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self,thismod,nom):
        uncrt = thismod['data'] if thismod else [0.0] * len(nom)
        maskval = [(x > 0 and y > 0) for x, y in zip(uncrt, nom)]
        mask = [maskval] * len(nom)
        return {'mask': mask, 'nom_data': nom, 'uncrt': uncrt}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'uncrt': [], 'nom_data': [], 'mask': []}
        )
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']
        self.mega_mods[key][s]['data']['uncrt'] += moddata['uncrt']
        self.mega_mods[key][s]['data']['nom_data'] += moddata['nom_data']

        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.shapesys.required_parset(
                defined_samp['data'], thismod['data']
        ))

class staterr_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self,thismod,nom):
        uncrt = thismod['data'] if thismod else [0.0] * len(nom)
        mask = [True if thismod else False] * len(nom)
        return {'mask': mask, 'nom_data': nom, 'uncrt': uncrt}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'uncrt': [], 'nom_data': [], 'mask': []}
        )
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']
        self.mega_mods[key][s]['data']['uncrt'] += moddata['uncrt']
        self.mega_mods[key][s]['data']['nom_data'] += moddata['nom_data']

        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.staterror.required_parset(
                defined_samp['data'], thismod['data']
        ))

class histosys_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self,thismod,nom):
        lo_data = thismod['data']['lo_data'] if thismod else nom
        hi_data = thismod['data']['hi_data'] if thismod else nom
        maskval = True if thismod else False
        mask = [maskval] * len(nom)
        return {'lo_data': lo_data, 'hi_data': hi_data, 'mask': mask, 'nom_data': nom}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'hi_data': [], 'lo_data': [], 'nom_data': [], 'mask': []}
        )
        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['lo_data'] += moddata['lo_data']
        self.mega_mods[key][s]['data']['hi_data'] += moddata['hi_data']
        self.mega_mods[key][s]['data']['nom_data'] += moddata['nom_data']
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']

        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.histosys.required_parset(
                defined_samp['data'], thismod['data']
        ))

class normsys_helper:
    def __init__(self, config):
        self.mega_mods = {}
        self.config = config
        self.parameters = {}

    def collect(self,thismod,nom):
        maskval = True if thismod else False
        lo_factor = thismod['data']['lo'] if thismod else 1.0
        hi_factor = thismod['data']['hi'] if thismod else 1.0
        nom_data = [1.0] * len(nom)
        lo = [lo_factor] * len(nom)  # broadcasting
        hi = [hi_factor] * len(nom)
        mask = [maskval] * len(nom)
        return {'lo': lo, 'hi': hi, 'mask': mask, 'nom_data': nom_data}

    def append(self,key,c,s,thismod,defined_samp):
        self.mega_mods.setdefault(key, {}).setdefault(s,{}).setdefault(
            'data',{'hi': [], 'lo': [], 'nom_data': [], 'mask': []}
        )

        nom = (
            defined_samp['data']
            if defined_samp
            else [0.0] * self.config.channel_nbins[c]
        )
        moddata = self.collect(thismod,nom)
        self.mega_mods[key][s]['data']['nom_data'] += moddata['nom_data']
        self.mega_mods[key][s]['data']['lo'] += moddata['lo']
        self.mega_mods[key][s]['data']['hi'] += moddata['hi']
        self.mega_mods[key][s]['data']['mask'] += moddata['mask']

        if thismod:
            self.parameters.setdefault(thismod['name'],[]).append(modifiers.normsys.required_parset(
                defined_samp['data'], thismod['data']
            ))



def _nominal_and_modifiers_from_spec(config, spec,batch_size):
    # the mega-channel will consist of mega-samples that subscribe to
    # mega-modifiers. i.e. while in normal histfactory, each sample might
    # be affected by some modifiers and some not, here we change it so that
    # samples are affected by all modifiers, but we set up the modifier
    # data such that the application of the modifier does not actually
    # change the bin value for bins that are not originally affected by
    # that modifier
    #
    # We don't actually set up the modifier data here for no-ops, but we do
    # set up the entire structure

    # helper maps channel-name/sample-name to pairs of channel-sample structs
    helper = {}
    for c in spec['channels']:
        for s in c['samples']:
            moddict = {f"{x['type']}/{x['name']}": x for x in s['modifiers']}
            helper.setdefault(c['name'], {})[s['name']] = (s, moddict)

    modifiers_helpers = {
        'histosys': histosys_helper(config),
        'normsys': normsys_helper(config),
        'normfactor': normfactor_helper(config),
        'shapefactor': shapefactor_helper(config),
        'lumi': lumi_helper(config),
        'shapesys': shapesys_helper(config),
        'staterror': staterr_helper(config)
    }

    nominal = nominal_helper(config)


    for c in config.channels:
        for s in config.samples:
            helper_data = helper.get(c, {}).get(s)
            defined_samp,defined_mods = (None,None) if not helper_data else helper_data
            nominal.append(c,s,defined_samp)
            for m, mtype in config.modifiers:
                key = f'{mtype}/{m}'
                # this is None if modifier doesn't affect channel/sample.
                thismod = defined_mods.get(key) if defined_mods else None
                modifiers_helpers[mtype].append(key,c,s,thismod,defined_samp)

    nominal_rates = nominal.apply()

    mega_mods = {k:v.mega_mods for k,v in modifiers_helpers.items()}


    _parset_reqs = {}
    for k,v in modifiers_helpers.items():
        for pname, req_list in v.parameters.items():
            _parset_reqs.setdefault(pname,[]).append(req_list)

    standard_modifiers = {
        k: c(
            [x for x in config.modifiers if x[1] == k],  # x[1] is mtype
            config,
            mega_mods.get(k),
            batch_size=batch_size,
            **config.modifier_settings.get(k, {}),
        )
        for k, c in modifiers.combined.items()
    }

    return standard_modifiers, nominal_rates


class _ModelConfig(_ChannelSummaryMixin):
    def __init__(self, spec, **config_kwargs):
        super().__init__(channels=spec['channels'])

        default_modifier_settings = {
            'normsys': {'interpcode': 'code4'},
            'histosys': {'interpcode': 'code4p'},
        }

        self.modifier_settings = config_kwargs.pop(
            'modifier_settings', default_modifier_settings
        )

        # if config_kwargs:
        #     raise exceptions.Unsupported(
        #         f"Unsupported options were passed in: {list(config_kwargs.keys())}."
        #     )

        self.par_map = {}
        self.par_order = []
        self.poi_name = None
        self.poi_index = None
        self.auxdata = []
        self.auxdata_order = []
        self.nmaindata = sum(self.channel_nbins.values())


    def set_parameters(self,poi_name,_required_paramsets):
        self._create_and_register_paramsets(_required_paramsets)
        if poi_name is not None:
            self.set_poi(poi_name)

        self.npars = len(self.suggested_init())

    def suggested_init(self):
        init = []
        for name in self.par_order:
            init = init + self.par_map[name]['paramset'].suggested_init
        return init

    def suggested_bounds(self):
        bounds = []
        for name in self.par_order:
            bounds = bounds + self.par_map[name]['paramset'].suggested_bounds
        return bounds

    def par_slice(self, name):
        return self.par_map[name]['slice']

    def param_set(self, name):
        return self.par_map[name]['paramset']

    def suggested_fixed(self):
        """
        Identify the fixed parameters in the model.

        Returns:
            List: A list of booleans, ``True`` for fixed and ``False`` for not fixed.

        Something like the following to build fixed_vals appropriately:

        .. code:: python

            fixed_pars = pdf.config.suggested_fixed()
            inits = pdf.config.suggested_init()
            fixed_vals = [
                (index, init)
                for index, (init, is_fixed) in enumerate(zip(inits, fixed_pars))
                if is_fixed
            ]
        """
        fixed = []
        for name in self.par_order:
            paramset = self.par_map[name]['paramset']
            fixed = fixed + [paramset.suggested_fixed] * paramset.n_parameters
        return fixed

    def set_poi(self, name):
        if name not in [x for x, _ in self.modifiers]:
            raise exceptions.InvalidModel(
                f"The parameter of interest '{name:s}' cannot be fit as it is not declared in the model specification."
            )
        s = self.par_slice(name)
        assert s.stop - s.start == 1
        self.poi_name = name
        self.poi_index = s.start

    def _create_and_register_paramsets(self, required_paramsets):
        next_index = 0
        for param_name, paramset in required_paramsets.items():
            log.info(
                'adding modifier %s (%s new nuisance parameters)',
                param_name,
                paramset.n_parameters,
            )

            sl = slice(next_index, next_index + paramset.n_parameters)
            next_index = next_index + paramset.n_parameters

            self.par_order.append(param_name)
            self.par_map[param_name] = {'slice': sl, 'paramset': paramset}


class _ConstraintModel:
    """Factory class to create pdfs for the constraint terms."""

    def __init__(self, config, batch_size):
        self.batch_size = batch_size
        self.config = config

        self.constraints_gaussian = gaussian_constraint_combined(
            config, batch_size=self.batch_size
        )
        self.constraints_poisson = poisson_constraint_combined(
            config, batch_size=self.batch_size
        )

        self.viewer_aux = ParamViewer(
            (self.batch_size or 1, self.config.npars),
            self.config.par_map,
            self.config.auxdata_order,
        )

        assert self.constraints_gaussian.batch_size == self.batch_size
        assert self.constraints_poisson.batch_size == self.batch_size

        indices = []
        if self.constraints_gaussian.has_pdf():
            indices.append(self.constraints_gaussian._normal_data)
        if self.constraints_poisson.has_pdf():
            indices.append(self.constraints_poisson._poisson_data)
        if self.has_pdf():
            self.constraints_tv = _TensorViewer(indices, self.batch_size)

    def has_pdf(self):
        """
        Indicate whether this model has a constraint.

        Returns:
            Bool: Whether the model has a constraint term

        """
        return self.constraints_gaussian.has_pdf() or self.constraints_poisson.has_pdf()

    def make_pdf(self, pars):
        """
        Construct a pdf object for a given set of parameter values.

        Args:
            pars (:obj:`tensor`): The model parameters

        Returns:
            pdf: A distribution object implementing the constraint pdf of HistFactory.
                 Either a Poissonn, a Gaussian or a joint pdf of both depending on the
                 constraints used in the specification.

        """
        pdfobjs = []

        gaussian_pdf = self.constraints_gaussian.make_pdf(pars)
        if gaussian_pdf:
            pdfobjs.append(gaussian_pdf)

        poisson_pdf = self.constraints_poisson.make_pdf(pars)
        if poisson_pdf:
            pdfobjs.append(poisson_pdf)

        if pdfobjs:
            simpdf = prob.Simultaneous(pdfobjs, self.constraints_tv, self.batch_size)
            return simpdf

    def logpdf(self, auxdata, pars):
        """
        Compute the logarithm of the value of the probability density.

        Args:
            auxdata (:obj:`tensor`): The auxiliary data (a subset of the full data in a HistFactory model)
            pars (:obj:`tensor`): The model parameters

        Returns:
            Tensor: The log of the pdf value

        """
        simpdf = self.make_pdf(pars)
        return simpdf.log_prob(auxdata)


class _MainModel:
    """Factory class to create pdfs for the main measurement."""

    def __init__(self, config, modifiers, nominal_rates, batch_size = None):
        self.config = config
        
        self._factor_mods = []
        self._delta_mods = []
        self.batch_size = batch_size

        self._nominal_rates = default_backend.tile(
            nominal_rates, (1, 1, self.batch_size or 1, 1)
        )

        self.modifiers_appliers = modifiers

        for k,v in self.modifiers_appliers.items():
            if v.op_code == 'addition':
                self._delta_mods.append(v.name)
            elif v.op_code == 'multiplication':
                self._factor_mods.append(v.name)

        self._precompute()
        events.subscribe('tensorlib_changed')(self._precompute)

    def _precompute(self):
        tensorlib, _ = get_backend()
        self.nominal_rates = tensorlib.astensor(self._nominal_rates)

    def has_pdf(self):
        """
        Indicate whether the main model exists.

        Returns:
            Bool: Whether the model has a Main Model component (yes it does)

        """
        return True

    def make_pdf(self, pars):
        lambdas_data = self.expected_data(pars)
        return prob.Independent(prob.Poisson(lambdas_data))

    def logpdf(self, maindata, pars):
        """
        Compute the logarithm of the value of the probability density.

        Args:
            maindata (:obj:`tensor`): The main channnel data (a subset of the full data in a HistFactory model)
            pars (:obj:`tensor`): The model parameters

        Returns:
            Tensor: The log of the pdf value

        """
        return self.make_pdf(pars).log_prob(maindata)

    def _modifications(self, pars):
        deltas = list(
            filter(
                lambda x: x is not None,
                [self.modifiers_appliers[k].apply(pars) for k in self._delta_mods],
            )
        )
        factors = list(
            filter(
                lambda x: x is not None,
                [self.modifiers_appliers[k].apply(pars) for k in self._factor_mods],
            )
        )

        return deltas, factors

    def expected_data(self, pars, return_by_sample=False):
        """
        Compute the expected rates for given values of parameters.

        For a single channel single sample, we compute:

            Pois(d | fac(pars) * (delta(pars) + nom) ) * Gaus(a | pars[is_gaus], sigmas) * Pois(a * cfac | pars[is_poi] * cfac)

        where:
            - delta(pars) is the result of an apply(pars) of combined modifiers
              with 'addition' op_code
            - factor(pars) is the result of apply(pars) of combined modifiers
              with 'multiplication' op_code
            - pars[is_gaus] are the subset of parameters that are constrained by
              gauss (with sigmas accordingly, some of which are computed by
              modifiers)
            - pars[is_pois] are the poissons and their rates (they come with
              their own additional factors unrelated to factor(pars) which are
              also computed by the finalize() of the modifier)

        So in the end we only make 3 calls to pdfs

            1. The pdf of data and modified rates
            2. All Gaussian constraint as one call
            3. All Poisson constraints as one call

        """
        tensorlib, _ = get_backend()
        pars = tensorlib.astensor(pars)
        deltas, factors = self._modifications(pars)

        allsum = tensorlib.concatenate(
            deltas + [self.nominal_rates]
        )

        nom_plus_delta = tensorlib.sum(allsum, axis=0)
        nom_plus_delta = tensorlib.reshape(
            nom_plus_delta, (1,) + tensorlib.shape(nom_plus_delta)
        )

        allfac = tensorlib.concatenate(factors + [nom_plus_delta])

        newbysample = tensorlib.product(allfac, axis=0)
        if return_by_sample:
            batch_first = tensorlib.einsum('ij...->ji...', newbysample)
            if self.batch_size is None:
                return batch_first[0]
            return batch_first

        newresults = tensorlib.sum(newbysample, axis=0)
        if self.batch_size is None:
            return newresults[0]
        return newresults


class Model:
    """The main pyhf model class."""

    def __init__(self, spec, custom_modifiers = None, batch_size=None, **config_kwargs):
        """
        Construct a HistFactory Model.

        Args:
            spec (:obj:`jsonable`): The HistFactory JSON specification
            batch_size (:obj:`None` or :obj:`int`): Number of simultaneous (batched) Models to compute.
            config_kwargs: Possible keyword arguments for the model configuration

        Returns:
            model (:class:`~pyhf.pdf.Model`): The Model instance.

        """
        custom_modifiers = custom_modifiers or []
        self.batch_size = batch_size
        self.spec = copy.deepcopy(spec)  # may get modified by config
        self.schema = config_kwargs.pop('schema', 'model.json')
        self.version = config_kwargs.pop('version', None)
        # run jsonschema validation of input specification against the (provided) schema
        log.info(f"Validating spec against schema: {self.schema:s}")
        utils.validate(self.spec, self.schema, version=self.version)
        # build up our representation of the specification
        self.config = _ModelConfig(self.spec,**config_kwargs)



        _required_paramsets = _paramset_requirements_from_modelspec(
            spec, self.config.channel_nbins,custom_modifiers_params = [
            c.required_parsets for c in custom_modifiers
        ]
        )
        poi_name = config_kwargs.pop('poi_name', 'mu')
        self.config.set_parameters(poi_name,_required_paramsets)

        standard_modifiers, _nominal_rates = _nominal_and_modifiers_from_spec(
            self.config, self.spec, self.batch_size
        )

        for custom in custom_modifiers:
            custom.config = self.config
            standard_modifiers[custom.name] = custom


        self.main_model = _MainModel(
            self.config,
            modifiers=standard_modifiers,
            nominal_rates=_nominal_rates,
            batch_size=self.batch_size,
        )

        # this is tricky, must happen before constraint
        # terms try to access auxdata but after
        # combined mods have been created that
        # set the aux data
        for k in sorted(self.config.par_map.keys()):
            parset = self.config.param_set(k)
            if hasattr(parset, 'pdf_type'):  # is constrained
                self.config.auxdata += parset.auxdata
                self.config.auxdata_order.append(k)
        self.config.nauxdata = len(self.config.auxdata)

        self.constraint_model = _ConstraintModel(
            config=self.config, batch_size=self.batch_size
        )

        sizes = []
        if self.main_model.has_pdf():
            sizes.append(self.config.nmaindata)
        if self.constraint_model.has_pdf():
            sizes.append(self.config.nauxdata)
        self.fullpdf_tv = _tensorviewer_from_sizes(
            sizes, ['main', 'aux'], self.batch_size
        )

    def expected_auxdata(self, pars):
        """
        Compute the expected value of the auxiliary measurements.

        Args:
            pars (:obj:`tensor`): The parameter values

        Returns:
            Tensor: The expected data of the auxiliary pdf

        """
        tensorlib, _ = get_backend()
        pars = tensorlib.astensor(pars)
        return self.make_pdf(pars)[1].expected_data()

    def _modifications(self, pars):
        return self.main_model._modifications(pars)

    @property
    def nominal_rates(self):
        """Nominal value of bin rates of the main model."""
        return self.main_model.nominal_rates

    def expected_actualdata(self, pars):
        """
        Compute the expected value of the main model.

        Args:
            pars (:obj:`tensor`): The parameter values

        Returns:
            Tensor: The expected data of the main model (no auxiliary data)

        """
        tensorlib, _ = get_backend()
        pars = tensorlib.astensor(pars)
        return self.make_pdf(pars)[0].expected_data()

    def expected_data(self, pars, include_auxdata=True):
        """
        Compute the expected value of the main model

        Args:
            pars (:obj:`tensor`): The parameter values

        Returns:
            Tensor: The expected data of the main and auxiliary model

        """
        tensorlib, _ = get_backend()
        pars = tensorlib.astensor(pars)
        if not include_auxdata:
            return self.make_pdf(pars)[0].expected_data()
        return self.make_pdf(pars).expected_data()

    def constraint_logpdf(self, auxdata, pars):
        """
        Compute the log value of the constraint pdf.

        Args:
            auxdata (:obj:`tensor`): The auxiliary measurement data
            pars (:obj:`tensor`): The parameter values

        Returns:
            Tensor: The log density value

        """
        return self.make_pdf(pars)[1].log_prob(auxdata)

    def mainlogpdf(self, maindata, pars):
        """
        Compute the log value of the main term.

        Args:
            maindata (:obj:`tensor`): The main measurement data
            pars (:obj:`tensor`): The parameter values

        Returns:
            Tensor: The log density value

        """
        return self.make_pdf(pars)[0].log_prob(maindata)

    def make_pdf(self, pars):
        """
        Construct a pdf object for a given set of parameter values.

        Args:
            pars (:obj:`tensor`): The model parameters

        Returns:
            pdf: A distribution object implementing the main measurement pdf of HistFactory

        """
        tensorlib, _ = get_backend()

        pdfobjs = []
        mainpdf = self.main_model.make_pdf(pars)
        if mainpdf:
            pdfobjs.append(mainpdf)
        constraintpdf = self.constraint_model.make_pdf(pars)
        if constraintpdf:
            pdfobjs.append(constraintpdf)

        simpdf = prob.Simultaneous(pdfobjs, self.fullpdf_tv, self.batch_size)
        return simpdf

    def logpdf(self, pars, data):
        """
        Compute the log value of the full density.

        Args:
            pars (:obj:`tensor`): The parameter values
            data (:obj:`tensor`): The measurement data

        Returns:
            Tensor: The log density value

        """
        try:
            tensorlib, _ = get_backend()
            pars, data = tensorlib.astensor(pars), tensorlib.astensor(data)
            # Verify parameter and data shapes
            if pars.shape[-1] != self.config.npars:
                raise exceptions.InvalidPdfParameters(
                    f'eval failed as pars has len {pars.shape[-1]} but {self.config.npars} was expected'
                )

            if data.shape[-1] != self.nominal_rates.shape[-1] + len(
                self.config.auxdata
            ):
                raise exceptions.InvalidPdfData(
                    f'eval failed as data has len {data.shape[-1]} but {self.config.nmaindata + self.config.nauxdata} was expected'
                )

            result = self.make_pdf(pars).log_prob(data)

            if (
                not self.batch_size
            ):  # force to be not scalar, should we changed with #522
                return tensorlib.reshape(result, (1,))
            return result
        except Exception:
            log.error(
                f"Eval failed for data {tensorlib.tolist(data)} pars: {tensorlib.tolist(pars)}",
                exc_info=True,
            )
            raise

    def pdf(self, pars, data):
        """
        Compute the density at a given observed point in data space of the full model.

        Args:
            pars (:obj:`tensor`): The parameter values
            data (:obj:`tensor`): The measurement data

        Returns:
            Tensor: The density value

        """
        tensorlib, _ = get_backend()
        return tensorlib.exp(self.logpdf(pars, data))
