from enum import Enum

import numpy as np

from PuzzleLib.Cuda.Driver import CuDnn
from PuzzleLib.Cuda.GPUArray import GPUArray
from PuzzleLib.Cuda.Wrappers.CuDnn import context

from PuzzleLib.Cuda.Utils import dtypesSupported, prod


class RNNAlgo(Enum):
	standard = CuDnn.RNN_ALGO_STANDARD
	persistStatic = CuDnn.RNN_ALGO_PERSIST_STATIC
	persistDynamic = CuDnn.RNN_ALGO_PERSIST_DYNAMIC


class RNNMode(Enum):
	relu = CuDnn.RNN_MODE_RELU
	tanh = CuDnn.RNN_MODE_TANH
	lstm = CuDnn.RNN_MODE_LSTM
	gru = CuDnn.RNN_MODE_GRU


class DirectionMode(Enum):
	uni = CuDnn.RNN_DIRECTION_UNIDIRECTIONAL
	bi = CuDnn.RNN_DIRECTION_BIDIRECTIONAL


def createRnn(insize, hsize, dtype, layers=1, algo=RNNAlgo.standard, mode=RNNMode.lstm, direction=DirectionMode.uni,
			  dropout=0.0, seed=0, batchsize=0):
	rnn = CuDnn.Rnn(
		context, insize, hsize, np.dtype(dtype), layers, algo.value, mode.value, direction.value,
		dropout, seed, batchsize
	)

	W = GPUArray.empty((rnn.wsize, ), dtype=dtype)
	params = acquireRnnParams(rnn, W)

	return rnn, W, params


def acquireRnnParams(rnn, W):
	mode = RNNMode(rnn.mode)

	if mode == RNNMode.relu or mode == RNNMode.tanh:
		return acquireNativeRnnParams(rnn, W)
	elif mode == RNNMode.lstm:
		return acquireLSTMParams(rnn, W)
	elif mode == RNNMode.gru:
		return acquireGRUParams(rnn, W)
	else:
		raise NotImplementedError(mode.value)


def getRnnParam(rnn, W, layer, linLayer, Wshape):
	Wtuple, biasTuple = rnn.getParam(W, layer, linLayer)

	Woffset, wsize = Wtuple
	biasOffset, biasSize = biasTuple

	dtype, gpudata = W.dtype, W.gpudata
	Wbytes, biasBytes = wsize * dtype.itemsize, biasSize * dtype.itemsize

	assert prod(Wshape) == wsize
	w = GPUArray(Wshape, dtype=W.dtype, gpudata=W.gpudata[Woffset:Woffset + Wbytes])

	bias = GPUArray((biasSize, ), dtype=W.dtype, gpudata=W.gpudata[biasOffset:biasOffset + biasBytes])
	return w, bias


def acquireNativeRnnParams(rnn, W):
	direction = DirectionMode(rnn.direction)

	linLayers = 2
	layers = rnn.layers if direction == DirectionMode.uni else rnn.layers * 2

	layerTypes = {0: "w", 1: "r"}

	params = []
	for layer in range(layers):
		layerparams = {}
		for linLayer in range(linLayers):
			if linLayer == 0:
				if layer == 0 or layer == 1 and direction == DirectionMode.bi:
					size = rnn.insize
				else:
					size = 2 * rnn.hsize if direction == DirectionMode.bi else rnn.hsize

				shape = (rnn.hsize, size)

			elif linLayer == 1:
				shape = (rnn.hsize, rnn.hsize)

			else:
				assert False

			w, bias = getRnnParam(rnn, W, layer, linLayer, shape)
			T = layerTypes[linLayer]

			Wname = "%si" % T
			assert Wname not in layerparams

			biasname = "b%si" % T
			assert biasname not in layerparams

			layerparams[Wname] = w
			layerparams[biasname] = bias

		params.append(layerparams)

	return params


def acquireLSTMParams(rnn, W):
	direction = DirectionMode(rnn.direction)

	linLayers = 8
	layers = rnn.layers if direction == DirectionMode.uni else rnn.layers * 2

	layerTypes = {
		0: "i", 4: "i",
		1: "f", 5: "f",
		2: "c", 6: "c",
		3: "o", 7: "o"
	}

	params = []
	for layer in range(layers):
		layerparams = {}
		for linLayer in range(linLayers):
			if linLayer < 4:
				if layer == 0 or layer == 1 and direction == DirectionMode.bi:
					size = rnn.insize
				else:
					size = 2 * rnn.hsize if direction == DirectionMode.bi else rnn.hsize

				shape, wtype = (rnn.hsize, size), "w"

			else:
				shape, wtype = (rnn.hsize, rnn.hsize), "r"

			w, bias = getRnnParam(rnn, W, layer, linLayer, shape)
			T = layerTypes[linLayer]

			Wname = "%s%s" % (wtype, T)
			assert Wname not in layerparams

			biasname = "b%s%s" % (wtype, T)
			assert biasname not in layerparams

			layerparams[Wname] = w
			layerparams[biasname] = bias

		params.append(layerparams)

	return params


def acquireGRUParams(rnn, W):
	direction = DirectionMode(rnn.direction)

	linLayers = 6
	layers = rnn.layers if direction == DirectionMode.uni else rnn.layers * 2

	layerTypes = {
		0: "r", 3: "r",
		1: "i", 4: "i",
		2: "h", 5: "h"
	}

	params = []
	for layer in range(layers):
		layerparams = {}
		for linLayer in range(linLayers):
			if linLayer < 3:
				if layer == 0 or layer == 1 and direction == DirectionMode.bi:
					size = rnn.insize
				else:
					size = 2 * rnn.hsize if direction == DirectionMode.bi else rnn.hsize

				shape, wtype = (rnn.hsize, size), "w"

			else:
				shape, wtype = (rnn.hsize, rnn.hsize), "r"

			w, bias = getRnnParam(rnn, W, layer, linLayer, shape)
			T = layerTypes[linLayer]

			Wname = "%s%s" % (wtype, T)
			assert Wname not in layerparams

			biasname = "b%s%s" % (wtype, T)
			assert biasname not in layerparams

			layerparams[Wname] = w
			layerparams[biasname] = bias

		params.append(layerparams)

	return params


def randomWInit(params):
	hostParams = []

	for layer in params:
		layerParams = {}

		for paramName, param in layer.items():
			hostParam = np.random.randn(*param.shape).astype(param.dtype)
			layerParams[paramName] = hostParam

			param.set(hostParam)

		hostParams.append(layerParams)

	return hostParams


def unittest():
	for dtype, atol in dtypesSupported():
		reluTest(dtype, atol)
		tanhTest(dtype, atol)
		lstmTest(dtype, atol)
		gruTest(dtype, atol)


def reluTest(dtype, atol):
	seqlen, batchsize, insize, hsize = 2, 3, 4, 5
	rnn, W, params = createRnn(insize, hsize, dtype, mode=RNNMode.relu)

	hostParams = randomWInit(params)[0]

	hostData = np.random.randn(seqlen, batchsize, insize).astype(dtype)
	hostHidden = np.random.randn(1, batchsize, hsize).astype(dtype)

	data, inithidden = GPUArray.toGpu(hostData), GPUArray.toGpu(hostHidden)
	outdata, trainReserve = rnn.forward(data, W, hidden=inithidden)

	hostOutData = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)

	hostOutData[0] = hostHidden
	for d in range(seqlen):
		res = np.dot(hostData[d], hostParams["wi"].T) + np.dot(hostOutData[d], hostParams["ri"].T) + \
			  hostParams["bwi"] + hostParams["bri"]
		hostOutData[d + 1] = (res > 0.0) * res

	assert np.allclose(hostOutData[1:], outdata.get(), atol=atol)

	hostGrad = np.random.randn(*outdata.shape).astype(dtype)

	grad = GPUArray.toGpu(hostGrad)
	ingrad, dhx, _ = rnn.backwardData(grad, outdata, W, trainReserve, hidden=inithidden)

	hostAccGrad = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostInGrad = np.zeros((seqlen, batchsize, insize), dtype=dtype)

	for d in range(seqlen):
		acc = (hostGrad[seqlen - d - 1] + np.dot(hostAccGrad[seqlen - d], hostParams["ri"])) * \
			  (hostOutData[seqlen - d] > 0)

		hostAccGrad[seqlen - d - 1] = acc
		hostInGrad[seqlen - d - 1] = np.dot(acc, hostParams["wi"])

	assert np.allclose(hostInGrad, ingrad.get(), atol=atol)

	dw = rnn.backwardParams(data, outdata, trainReserve, hidden=inithidden)
	dwparams = acquireRnnParams(rnn, W=dw)

	hostRiGrad = np.zeros(hostParams["ri"].shape, dtype=dtype)
	hostWiGrad = np.zeros(hostParams["wi"].shape, dtype=dtype)
	hostBiGrad = np.zeros(hostParams["bwi"].shape, dtype=dtype)

	for d in range(seqlen):
		hostRiGrad += np.dot(hostAccGrad[seqlen - d - 1].T, hostOutData[seqlen - d - 1])
		hostWiGrad += np.dot(hostAccGrad[seqlen - d - 1].T, hostData[seqlen - d - 1])
		hostBiGrad += np.sum(hostAccGrad[seqlen - d - 1], axis=0)

	assert np.allclose(hostRiGrad, dwparams[0]["ri"].get(), atol=atol)
	assert np.allclose(hostWiGrad, dwparams[0]["wi"].get(), atol=atol)
	assert np.allclose(hostBiGrad, dwparams[0]["bwi"].get(), atol=atol)
	assert np.allclose(hostBiGrad, dwparams[0]["bri"].get(), atol=atol)

	hostDhx = np.dot(hostAccGrad[0], hostParams["ri"])
	assert np.allclose(hostDhx, dhx.get(), atol=atol)


def tanhTest(dtype, atol):
	seqlen, batchsize, insize, hsize = 3, 3, 3, 2
	rnn, W, params = createRnn(insize, hsize, dtype, mode=RNNMode.tanh, direction=DirectionMode.bi)

	hostParams = randomWInit(params)
	hostData = np.random.randn(seqlen, batchsize, insize).astype(dtype)

	data = GPUArray.toGpu(hostData)
	outdata, trainReserve = rnn.forward(data, W)

	hostOutData = np.zeros((seqlen + 2, batchsize, 2 * hsize), dtype=dtype)

	for d in range(seqlen):
		res = np.dot(hostData[d], hostParams[0]["wi"].T) + \
			  np.dot(hostOutData[d, :, :hsize], hostParams[0]["ri"].T) + hostParams[0]["bwi"] + hostParams[0]["bri"]
		hostOutData[d + 1, :, :hsize] = np.tanh(res)

		res = np.dot(hostData[seqlen - d - 1], hostParams[1]["wi"].T) + \
			  np.dot(hostOutData[seqlen + 1 - d, :, hsize:], hostParams[1]["ri"].T) + \
			  hostParams[1]["bwi"] + hostParams[1]["bri"]
		hostOutData[seqlen - d, :, hsize:] = np.tanh(res)

	assert np.allclose(hostOutData[1:seqlen + 1], outdata.get(), atol=atol)

	hostGrad = np.random.randn(*outdata.shape).astype(dtype)

	grad = GPUArray.toGpu(hostGrad)
	ingrad, _, _ = rnn.backwardData(grad, outdata, W, trainReserve)

	hostAccGrad = np.zeros((seqlen + 2, batchsize, 2 * hsize), dtype=dtype)
	hostInGrad = np.zeros((seqlen, batchsize, insize), dtype=dtype)

	for d in range(seqlen):
		acc = (hostGrad[seqlen - d - 1, :, :hsize] +
			   np.dot(hostAccGrad[seqlen + 1 - d, :, :hsize], hostParams[0]["ri"])) * \
			  (1.0 - hostOutData[seqlen - d, :, :hsize]**2)

		hostAccGrad[seqlen - d, :, :hsize] = acc
		hostInGrad[seqlen - d - 1] += np.dot(acc, hostParams[0]["wi"])

		acc = (hostGrad[d, :, hsize:] + np.dot(hostAccGrad[d, :, hsize:], hostParams[1]["ri"])) * \
			  (1.0 - hostOutData[d + 1, :, hsize:]**2)

		hostAccGrad[d + 1, :, hsize:] = acc
		hostInGrad[d] += np.dot(acc, hostParams[1]["wi"])

	assert np.allclose(hostInGrad, ingrad.get(), atol=atol)

	dw = rnn.backwardParams(data, outdata, trainReserve)
	dwparams = acquireRnnParams(rnn, W=dw)

	hostRi0Grad = np.zeros(hostParams[0]["ri"].shape, dtype=dtype)
	hostRi1Grad = np.zeros(hostParams[1]["ri"].shape, dtype=dtype)
	hostWi0Grad = np.zeros(hostParams[0]["wi"].shape, dtype=dtype)
	hostWi1Grad = np.zeros(hostParams[1]["wi"].shape, dtype=dtype)

	hostBi0Grad = np.zeros(hostParams[0]["bwi"].shape, dtype=dtype)
	hostBi1Grad = np.zeros(hostParams[1]["bwi"].shape, dtype=dtype)

	for d in range(seqlen):
		hostRi0Grad += np.dot(hostAccGrad[seqlen - d + 1, :, :hsize].T, hostOutData[seqlen - d, :, :hsize])
		hostWi0Grad += np.dot(hostAccGrad[seqlen - d, :, :hsize].T, hostData[seqlen - d - 1])
		hostRi1Grad += np.dot(hostAccGrad[d, :, hsize:].T, hostOutData[d + 1, :, hsize:])
		hostWi1Grad += np.dot(hostAccGrad[d + 1, :, hsize:].T, hostData[d])

		hostBi0Grad += np.sum(hostAccGrad[seqlen - d, :, :hsize], axis=0)
		hostBi1Grad += np.sum(hostAccGrad[d + 1, :, hsize:], axis=0)

	assert np.allclose(hostRi0Grad, dwparams[0]["ri"].get(), atol=atol)
	assert np.allclose(hostWi0Grad, dwparams[0]["wi"].get(), atol=atol)
	assert np.allclose(hostRi1Grad, dwparams[1]["ri"].get(), atol=atol)
	assert np.allclose(hostWi1Grad, dwparams[1]["wi"].get(), atol=atol)

	assert np.allclose(hostBi0Grad, dwparams[0]["bwi"].get(), atol=atol)
	assert np.allclose(hostBi0Grad, dwparams[0]["bri"].get(), atol=atol)

	assert np.allclose(hostBi1Grad, dwparams[1]["bwi"].get(), atol=atol)
	assert np.allclose(hostBi1Grad, dwparams[1]["bri"].get(), atol=atol)


def lstmTest(dtype, atol):
	seqlen, batchsize, insize, hsize = 4, 2, 4, 2
	rnn, W, params = createRnn(insize, hsize, dtype, mode=RNNMode.lstm)

	hostParams = randomWInit(params)[0]

	hostData = np.random.randn(seqlen, batchsize, insize).astype(dtype)
	hostInitHidden = np.random.randn(1, batchsize, hsize).astype(dtype)
	hostInitCells = np.ones((1, batchsize, hsize), dtype=dtype)

	data = GPUArray.toGpu(hostData)
	inithidden, initcells = GPUArray.toGpu(hostInitHidden), GPUArray.toGpu(hostInitCells)

	outdata, trainReserve = rnn.forward(data, W, hidden=inithidden, cells=initcells)

	hostOutData = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostCells = np.empty((seqlen + 1, batchsize, hsize), dtype=dtype)

	hostOutData[0] = hostInitHidden
	hostCells[0] = hostInitCells

	hostStates = np.zeros((seqlen + 2, batchsize, hsize * 4), dtype=dtype)
	hostW = np.empty((insize + hsize, 4 * hsize), dtype=dtype)
	hostBias = np.empty((4 * hsize, ), dtype=dtype)

	hostW[:insize, :hsize] = hostParams["wc"].T
	hostW[:insize, hsize:2 * hsize] = hostParams["wi"].T
	hostW[:insize, 2 * hsize:3 * hsize] = hostParams["wf"].T
	hostW[:insize, 3 * hsize:] = hostParams["wo"].T

	hostW[insize:, :hsize] = hostParams["rc"].T
	hostW[insize:, hsize:2 * hsize] = hostParams["ri"].T
	hostW[insize:, 2 * hsize:3 * hsize] = hostParams["rf"].T
	hostW[insize:, 3 * hsize:] = hostParams["ro"].T

	hostBias[:hsize] = hostParams["bwc"] + hostParams["brc"]
	hostBias[hsize:2 * hsize] = hostParams["bwi"] + hostParams["bri"]
	hostBias[2 * hsize: 3 * hsize] = hostParams["bwf"] + hostParams["brf"]
	hostBias[3 * hsize:] = hostParams["bwo"] + hostParams["bro"]

	def lstmAct(dat, hsz):
		dat[:, :hsz] = np.tanh(dat[:, :hsz])
		dat[:, hsz:] = 1.0 / (np.exp(-dat[:, hsz:]) + 1.0)
		return dat

	for d in range(seqlen):
		inp = np.hstack((hostData[d], hostOutData[d]))
		outp = lstmAct(np.dot(inp, hostW) + hostBias, hsize)
		hostStates[d + 1] = outp

		ct = outp[:, 2 * hsize:3 * hsize] * hostCells[d] + outp[:, hsize :2 * hsize] * outp[:, :hsize]

		hostCells[d + 1] = ct
		hostOutData[d + 1] = outp[:, 3 * hsize:] * np.tanh(ct)

	assert np.allclose(hostOutData[1:], outdata.get(), atol=atol)

	hostGrad = np.random.randn(*outdata.shape).astype(dtype)

	grad = GPUArray.toGpu(hostGrad)
	ingrad, dhx, dcx = rnn.backwardData(grad, outdata, W, trainReserve, hidden=inithidden, cells=initcells)

	dw = rnn.backwardParams(data, outdata, trainReserve, hidden=inithidden)
	dwparams = acquireRnnParams(rnn, W=dw)

	dwparams = dwparams[0]
	hostDw = np.zeros(hostW.shape, dtype=dtype)
	hostDb = np.zeros(hostBias.shape, dtype=dtype)

	hostAccCellsGrad = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostAccHiddenGrad = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostInGrad = np.zeros((seqlen, batchsize, insize), dtype=dtype)

	def lstmActBwd(gr, dat, hsz):
		gr[:, :hsz] = gr[:, :hsz] * (1.0 - dat[:, :hsz]**2)
		gr[:, hsz:] = gr[:, hsz:] * dat[:, hsz:] * (1.0 - dat[:, hsz:])
		return gr

	for d in range(seqlen):
		dh = hostGrad[seqlen-1 - d] + hostAccHiddenGrad[seqlen - d]
		dc = dh * hostStates[seqlen-d, :, 3 * hsize:] * (1 - np.tanh(hostCells[seqlen - d])**2) + \
			 hostAccCellsGrad[seqlen - d] * hostStates[seqlen + 1 - d, :, 2 * hsize:3 * hsize]

		layergr = np.empty((batchsize, 4 * hsize), dtype=dtype)
		layergr[:, :hsize] = dc * hostStates[seqlen-d, :, hsize:2 * hsize]
		layergr[:, hsize:2 * hsize] = dc * hostStates[seqlen-d, :, :hsize]
		layergr[:, 2 * hsize:3 * hsize] = dc * hostCells[seqlen - 1 - d]
		layergr[:, 3 * hsize:] = dh * np.tanh(hostCells[seqlen - d])

		layergr = lstmActBwd(layergr, hostStates[seqlen - d], hsize)
		ingr = np.dot(layergr, hostW.T)

		indata = np.hstack((hostData[seqlen - 1 - d], hostOutData[seqlen - 1 - d]))
		hostDw += np.dot(indata.T, layergr)
		hostDb += np.sum(layergr, axis=0)

		hostAccHiddenGrad[seqlen-1 - d] = ingr[:, insize:]
		hostAccCellsGrad[seqlen-1 - d] = dc
		hostInGrad[seqlen-1 - d] = ingr[:, :insize]

	assert np.allclose(hostInGrad, ingrad.get(), atol=atol)

	assert np.allclose(hostDw[:insize, :hsize], dwparams["wc"].get().T, atol=atol)
	assert np.allclose(hostDw[:insize, hsize:2 * hsize], dwparams["wi"].get().T, atol=atol)
	assert np.allclose(hostDw[:insize, 2 * hsize:3 * hsize], dwparams["wf"].get().T, atol=atol)
	assert np.allclose(hostDw[:insize, 3 * hsize:], dwparams["wo"].get().T, atol=atol)

	assert np.allclose(hostDw[insize:, :hsize], dwparams["rc"].get().T, atol=atol)
	assert np.allclose(hostDw[insize:, hsize:2 * hsize], dwparams["ri"].get().T, atol=atol)
	assert np.allclose(hostDw[insize:, 2 * hsize:3 * hsize], dwparams["rf"].get().T, atol=atol)
	assert np.allclose(hostDw[insize:, 3 * hsize:], dwparams["ro"].get().T, atol=atol)

	assert np.allclose(hostDb[:hsize], dwparams["bwc"].get(), atol=atol)
	assert np.allclose(hostDb[:hsize], dwparams["brc"].get(), atol=atol)

	assert np.allclose(hostDb[hsize:2 * hsize], dwparams["bwi"].get(), atol=atol)
	assert np.allclose(hostDb[hsize:2 * hsize], dwparams["bri"].get(), atol=atol)

	assert np.allclose(hostDb[2 * hsize: 3 * hsize], dwparams["bwf"].get(), atol=atol)
	assert np.allclose(hostDb[2 * hsize: 3 * hsize], dwparams["brf"].get(), atol=atol)

	assert np.allclose(hostDb[3 * hsize:], dwparams["bwo"].get(), atol=atol)
	assert np.allclose(hostDb[3 * hsize:], dwparams["bro"].get(), atol=atol)


def gruTest(dtype, atol):
	seqlen, batchsize, insize, hsize = 3, 3, 4, 2
	rnn, W, params = createRnn(insize, hsize, dtype, mode=RNNMode.gru)

	hostParams = randomWInit(params)[0]

	hostData = np.random.randn(seqlen, batchsize, insize).astype(dtype)
	hostInitHidden = np.random.randn(1, batchsize, hsize).astype(dtype)

	data, inithidden = GPUArray.toGpu(hostData), GPUArray.toGpu(hostInitHidden)
	outdata, trainReserve = rnn.forward(data, W, hidden=inithidden)

	hostOutData = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostOutData[0] = hostInitHidden

	hostStates = np.zeros((seqlen + 1, batchsize, hsize * 4), dtype=dtype)
	hostHts = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostW = np.zeros((insize + hsize, 4 * hsize), dtype=dtype)
	hostBias = np.empty((4 * hsize, ), dtype=dtype)

	hostW[:insize, hsize:2 * hsize] = hostParams["wh"].T
	hostW[:insize, 2 * hsize:3 * hsize] = hostParams["wr"].T
	hostW[:insize, 3 * hsize:] = hostParams["wi"].T

	hostW[insize:, :hsize] = hostParams["rh"].T
	hostW[insize:, 2 * hsize:3 * hsize] = hostParams["rr"].T
	hostW[insize:, 3 * hsize:] = hostParams["ri"].T

	hostBias[:hsize] = hostParams["brh"]
	hostBias[hsize:2 * hsize] = hostParams["bwh"]
	hostBias[2 * hsize: 3 * hsize] = hostParams["bwr"] + hostParams["brr"]
	hostBias[3 * hsize:] = hostParams["bwi"] + hostParams["bri"]

	def gruAct(dat, hsz):
		dat[:, 2 * hsz:] = 1.0 / (np.exp(-dat[:, 2 * hsz:]) + 1.0)
		return dat

	for d in range(seqlen):
		inp = np.hstack((hostData[d], hostOutData[d]))
		outp = gruAct(np.dot(inp, hostW) + hostBias, hsize)
		hostStates[d + 1] = outp

		ht = np.tanh(outp[:, hsize:2 * hsize] + outp[:, 2 * hsize: 3 * hsize] * outp[:, :hsize])
		it = outp[:, 3 * hsize:]
		hostOutData[d + 1] = (1.0 - it) * ht + it * hostOutData[d]
		hostHts[d + 1] = ht

	assert np.allclose(hostOutData[1:], outdata.get(), atol=atol)

	hostGrad = np.random.randn(*outdata.shape).astype(dtype)

	grad = GPUArray.toGpu(hostGrad)
	ingrad, dhx, _ = rnn.backwardData(grad, outdata, W, trainReserve, hidden=inithidden)

	dw = rnn.backwardParams(data, outdata, trainReserve, hidden=inithidden)
	dwparams = acquireRnnParams(rnn, W=dw)

	dwparams = dwparams[0]
	hostDw = np.zeros(hostW.shape, dtype=dtype)
	hostDb = np.zeros(hostBias.shape, dtype=dtype)

	hostAccGrad = np.zeros((seqlen + 1, batchsize, hsize), dtype=dtype)
	hostInGrad = np.zeros((seqlen, batchsize, insize), dtype=dtype)

	def gruActBwd(gr, dat, hsz):
		gr[:, 2 * hsz:] = gr[:, 2 * hsz:] * dat[:, 2 * hsz:] * (1.0 - dat[:, 2 * hsz:])
		return gr

	for d in range(seqlen):
		dh = hostGrad[seqlen-1 - d] + hostAccGrad[seqlen - d]
		dht = (1 - hostStates[seqlen - d, :, 3 * hsize:]) * dh

		layergr = np.empty((batchsize, 4 * hsize), dtype=dtype)
		layergr[:, :hsize] = dht * (1.0 - hostHts[seqlen - d]**2) * hostStates[seqlen - d, :, 2 * hsize:3 * hsize]
		layergr[:, hsize:2 * hsize] = dht * (1.0 - hostHts[seqlen - d]**2)
		layergr[:, 2 * hsize:3 * hsize] = dht * (1.0 - hostHts[seqlen - d]**2) * hostStates[seqlen - d, :, :hsize]
		layergr[:, 3 * hsize:] = dh * (hostOutData[seqlen - 1 - d] - hostHts[seqlen - d])

		layergr = gruActBwd(layergr, hostStates[seqlen - d], hsize)
		ingr = np.dot(layergr, hostW.T)

		indata = np.hstack((hostData[seqlen - 1 - d], hostOutData[seqlen - 1 - d]))
		hostDw += np.dot(indata.T, layergr)
		hostDb += np.sum(layergr, axis=0)

		hostAccGrad[seqlen - 1 - d] = dh * hostStates[seqlen - d, :, 3 * hsize:] + ingr[:, insize:]
		hostInGrad[seqlen - 1 - d] = ingr[:, :insize]

	assert np.allclose(hostInGrad, ingrad.get(), atol=atol)

	assert np.allclose(hostDw[:insize, hsize:2 * hsize], dwparams["wh"].get().T, atol=atol)
	assert np.allclose(hostDw[:insize, 2 * hsize:3 * hsize], dwparams["wr"].get().T, atol=atol)
	assert np.allclose(hostDw[:insize, 3 * hsize:], dwparams["wi"].get().T, atol=atol)

	assert np.allclose(hostDw[insize:, :hsize], dwparams["rh"].get().T, atol=atol)
	assert np.allclose(hostDw[insize:, 2 * hsize:3 * hsize], dwparams["rr"].get().T, atol=atol)
	assert np.allclose(hostDw[insize:, 3 * hsize:], dwparams["ri"].get().T, atol=atol)

	assert np.allclose(hostDb[:hsize], dwparams["brh"].get(), atol=atol)
	assert np.allclose(hostDb[hsize:2 * hsize], dwparams["bwh"].get(), atol=atol)

	assert np.allclose(hostDb[2 * hsize: 3 * hsize], dwparams["bwr"].get(), atol=atol)
	assert np.allclose(hostDb[2 * hsize: 3 * hsize], dwparams["brr"].get(), atol=atol)

	assert np.allclose(hostDb[3 * hsize:], dwparams["bwi"].get(), atol=atol)
	assert np.allclose(hostDb[3 * hsize:], dwparams["bri"].get(), atol=atol)


if __name__ == "__main__":
	unittest()
